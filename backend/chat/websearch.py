"""web_search tool: query the local SearXNG instance, then read the top result pages and
keep only the passages relevant to the query, so the model gets fresh, compact context."""
import ipaddress
import re
import socket
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from urllib.parse import urljoin

import httpcore
import httpx
from django.conf import settings
from django.utils import timezone

MAX_QUERY = 300
MAX_RESULTS = 5          # search results listed to the model
FETCH_PAGES = 3          # of those, pages actually opened and read
PAGE_MAX_BYTES = 1_500_000
PAGE_TIMEOUT = httpx.Timeout(8.0, connect=4.0)
MAX_REDIRECTS = 3
EXCERPT_CHARS = 1200     # relevant text kept per page
RESULT_CHARS = 5000      # total tool output, keeps the model's context small
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) gemma-chat/1.0 (+local web_search tool)"

STOPWORDS = set("""a an and are as at be by for from has have how i in is it its of on or that the this
to was what when where which who why will with does do did latest current now today new""".split())


class SearchError(Exception):
    pass


# --- Fetching pages without reaching local or private networks (SSRF protection) ---

def _public_ip(host, port):
    """Resolve host and return an address only if *every* address it resolves to is public."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise httpcore.ConnectError(f"Cannot resolve {host}") from exc
    for *_, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0].split("%")[0])
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global:
            raise httpcore.ConnectError("Blocked a non-public address")
    return infos[0][4][0]


class _PublicOnlyBackend(httpcore.SyncBackend):
    # Checked at connect time, for every connection including redirects, so DNS
    # rebinding can't swap in a private address after validation.
    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        return super().connect_tcp(_public_ip(host, port), port, timeout, local_address, socket_options)


def _page_client():
    transport = httpx.HTTPTransport()
    transport._pool = httpcore.ConnectionPool(  # same pool httpx builds, plus the IP check
        ssl_context=httpx.create_ssl_context(), network_backend=_PublicOnlyBackend(), max_connections=FETCH_PAGES,
    )
    return httpx.Client(transport=transport, timeout=PAGE_TIMEOUT, trust_env=False,
                        headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain;q=0.9"})


def _allowed_url(url):
    try:
        u = httpx.URL(url)
    except (httpx.InvalidURL, TypeError):
        return False
    return u.scheme in ("http", "https") and u.port in (None, 80, 443) and not u.userinfo and bool(u.host)


def fetch_page_text(client, url):
    """Return the visible text blocks of an HTML/plain-text page (empty list on failure)."""
    for _ in range(MAX_REDIRECTS + 1):
        if not _allowed_url(url):
            return []
        try:
            with client.stream("GET", url) as r:
                if r.is_redirect and r.headers.get("location"):
                    url = urljoin(url, r.headers["location"])
                    continue
                ctype = r.headers.get("content-type", "").lower()
                if r.status_code != 200 or not ctype.startswith(("text/html", "application/xhtml", "text/plain")):
                    return []
                body = bytearray()
                for chunk in r.iter_bytes():
                    body += chunk
                    if len(body) > PAGE_MAX_BYTES:
                        break
                text = bytes(body).decode(r.encoding or "utf-8", "replace")
        except httpx.HTTPError:
            return []
        return html_blocks(text) if "html" in ctype else [" ".join(p.split()) for p in text.split("\n\n") if p.strip()]
    return []


# --- Text extraction and passage selection ---

class _TextExtractor(HTMLParser):
    SKIP = {"head", "script", "style", "noscript", "svg", "nav", "footer", "header", "form",
            "aside", "iframe", "template", "button", "select", "dialog"}
    BLOCK = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "td", "th", "br", "article",
             "section", "blockquote", "pre", "dd", "dt", "table", "ul", "ol", "main", "figcaption"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.blocks = []
        self.buf = []

    def flush(self):
        text = " ".join("".join(self.buf).split())
        if text:
            self.blocks.append(text)
        self.buf = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.flush()

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self.flush()

    def handle_data(self, data):
        if not self.skip:
            self.buf.append(data)


def html_blocks(html):
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    parser.flush()
    return parser.blocks


def _terms(text):
    return {w for w in re.findall(r"\w+", text.lower()) if len(w) > 1 and w not in STOPWORDS}


def relevant_excerpt(blocks, query, limit=EXCERPT_CHARS):
    """Pick the text blocks that share the most terms with the query, kept in page order."""
    terms = _terms(query)
    candidates = [(i, b) for i, b in enumerate(blocks) if len(b) >= 40]
    scores = {i: len(terms & _terms(b)) for i, b in candidates}
    matching = [(i, b) for i, b in candidates if scores[i]]
    # Best matches first; if nothing matches, fall back to the start of the page
    ranked = sorted(matching, key=lambda ib: (-scores[ib[0]], ib[0])) if matching else candidates
    chosen, used = [], 0
    for i, block in ranked:
        if limit - used < 40:
            break
        block = block[: limit - used]
        chosen.append((i, block))
        used += len(block) + 1
    return "\n".join(b for _, b in sorted(chosen))


# --- Tool entry point ---

def search(query):
    """Raw SearXNG results: list of dicts with title, url, content and publishedDate."""
    try:
        r = httpx.get(f"{settings.SEARXNG_URL}/search", timeout=12.0,
                      params={"q": query, "format": "json", "safesearch": 1},
                      headers={"X-Real-IP": "127.0.0.1"})  # SearXNG's bot detection expects it
        r.raise_for_status()
        results = r.json().get("results", [])
    except (httpx.HTTPError, ValueError) as exc:
        raise SearchError("The search service is not reachable.") from exc
    seen, out = set(), []
    for item in results:
        url = item.get("url") or ""
        if url in seen or not _allowed_url(url):
            continue
        seen.add(url)
        out.append(item)
        if len(out) == MAX_RESULTS:
            break
    return out


def web_search(query):
    """Run the tool. Returns (text for the model, [(title, url), ...] sources)."""
    query = " ".join(str(query).split())[:MAX_QUERY]
    if not query:
        return "web_search needs a non-empty query.", []
    try:
        results = search(query)
    except SearchError as exc:
        return f"Web search failed: {exc} Answer from your own knowledge and say it may be outdated.", []
    if not results:
        return f'No web results for "{query}".', []

    with _page_client() as client, ThreadPoolExecutor(FETCH_PAGES) as pool:
        pages = list(pool.map(lambda item: fetch_page_text(client, item["url"]), results[:FETCH_PAGES]))
    pages += [[]] * (len(results) - len(pages))

    lines = [f'Web results for "{query}" (retrieved {timezone.localdate().isoformat()}):']
    for n, (item, blocks) in enumerate(zip(results, pages), 1):
        title = " ".join((item.get("title") or item["url"]).split())
        date = (item.get("publishedDate") or "")[:10]
        lines.append(f"\n[{n}] {title}\nURL: {item['url']}" + (f"\nPublished: {date}" if date else ""))
        if item.get("content"):
            lines.append("Snippet: " + " ".join(item["content"].split()))
        excerpt = relevant_excerpt(blocks, query) if blocks else ""
        if excerpt:
            lines.append("From the page:\n" + excerpt)
    text = "\n".join(lines)
    if len(text) > RESULT_CHARS:
        text = text[:RESULT_CHARS] + "\n[truncated]"
    sources = [(" ".join((i.get("title") or i["url"]).split()), i["url"]) for i in results]
    return text, sources
