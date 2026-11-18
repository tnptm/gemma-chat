import socket
from unittest import mock

import httpx
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APITestCase

from control.models import OllamaConfig

from . import ollama, websearch
from .models import Conversation, Message
from .views import format_sources, markdown_text

User = get_user_model()


def addrinfo(ip):
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return lambda *a, **k: [(family, socket.SOCK_STREAM, 6, "", (ip, 80))]


class PageFetchSafetyTests(SimpleTestCase):
    def test_non_public_addresses_are_rejected(self):
        for ip in ["127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "::1", "::ffff:127.0.0.1", "fd00::1"]:
            with self.subTest(ip=ip), mock.patch.object(socket, "getaddrinfo", addrinfo(ip)):
                with self.assertRaises(Exception):
                    websearch._public_ip("example.com", 80)
        with mock.patch.object(socket, "getaddrinfo", addrinfo("93.184.215.14")):
            self.assertEqual(websearch._public_ip("example.com", 80), "93.184.215.14")

    def test_client_checks_address_at_connect_time(self):
        # A public-looking name that resolves to loopback must not be fetched
        with mock.patch.object(socket, "getaddrinfo", addrinfo("127.0.0.1")), websearch._page_client() as client:
            with self.assertRaisesRegex(httpx.ConnectError, "non-public"):
                client.get("http://rebind.example/")
            self.assertEqual(websearch.fetch_page_text(client, "http://rebind.example/"), [])

    def test_allowed_urls(self):
        self.assertTrue(websearch._allowed_url("https://example.com/a?b=1"))
        for url in ["ftp://example.com/", "http://example.com:11434/", "http://user:pw@example.com/",
                    "file:///etc/passwd", "javascript:alert(1)", ""]:
            self.assertFalse(websearch._allowed_url(url), url)


class TextExtractionTests(SimpleTestCase):
    def test_html_blocks_skip_scripts_and_navigation(self):
        html = ("<html><head><title>T</title><script>var x=1</script></head><body><nav>Menu</nav>"
                "<p>First &amp; paragraph</p><div>Second <b>block</b></div><footer>Foot</footer></body></html>")
        self.assertEqual(websearch.html_blocks(html), ["First & paragraph", "Second block"])

    def test_relevant_excerpt_prefers_matching_blocks_in_page_order(self):
        blocks = ["Cookie banner text that is long enough to count here.",
                  "Python 3.15.2 was released on October 20, 2026 with bug fixes.",
                  "Unrelated sidebar content about something else entirely, long.",
                  "Python release schedule: 3.15 is the newest major Python release."]
        excerpt = websearch.relevant_excerpt(blocks, "newest Python release", limit=140)
        self.assertIn("3.15.2", excerpt)
        self.assertIn("schedule", excerpt)
        self.assertNotIn("Cookie", excerpt)
        self.assertLess(excerpt.index("3.15.2"), excerpt.index("schedule"))


class WebSearchToolTests(SimpleTestCase):
    def test_formats_results_with_page_excerpts(self):
        results = [{"title": "Python 3.15.2", "url": "https://python.org/r", "content": "Snippet",
                    "publishedDate": "2026-10-20T00:00:00"},
                   {"title": "Other", "url": "https://example.com/", "content": ""}]
        with mock.patch.object(websearch, "search", return_value=results), \
                mock.patch.object(websearch, "fetch_page_text",
                                  side_effect=lambda c, u: ["Python 3.15.2 is the newest Python release today."]):
            text, sources = websearch.web_search("  newest   python ")
        self.assertIn('Web results for "newest python"', text)
        self.assertIn("Published: 2026-10-20", text)
        self.assertIn("From the page:\nPython 3.15.2", text)
        self.assertEqual(sources, [("Python 3.15.2", "https://python.org/r"), ("Other", "https://example.com/")])

    def test_search_failure_is_reported_to_the_model(self):
        with mock.patch.object(httpx, "get", side_effect=httpx.ConnectError("down")):
            text, sources = websearch.web_search("anything")
        self.assertIn("Web search failed", text)
        self.assertEqual(sources, [])

    def test_search_drops_unsafe_and_duplicate_urls(self):
        payload = {"results": [{"url": "https://a.example/"}, {"url": "https://a.example/"},
                               {"url": "javascript:alert(1)"}, {"url": "https://b.example/"}]}
        with mock.patch.object(httpx, "get", return_value=httpx.Response(200, json=payload, request=httpx.Request("GET", "http://s"))):
            urls = [r["url"] for r in websearch.search("q")]
        self.assertEqual(urls, ["https://a.example/", "https://b.example/"])


CFG = OllamaConfig(active_model="picked:model", host="127.0.0.1:11434", context_length=4096, keep_alive="10m")


def chunks(*messages):
    return [{"message": m, "done": False} for m in messages] + [{"message": {}, "done": True}]


class ToolLoopTests(SimpleTestCase):
    @override_settings(WEB_SEARCH_ENABLED=True)
    def test_tool_call_runs_search_and_answers(self):
        call = {"function": {"name": "web_search", "arguments": {"query": "python latest"}}}
        bodies = []

        def fake_stream(cfg, body):
            bodies.append(body)
            return iter(chunks({"tool_calls": [call]}) if len(bodies) == 1 else chunks({"content": "It is 3.15.2."}))

        with mock.patch.object(ollama, "_stream", side_effect=fake_stream), \
                mock.patch.object(websearch, "web_search", return_value=("RESULTS", [("T", "https://t.example/")])) as ws:
            events = list(ollama.stream_chat([{"role": "user", "content": "latest python?"}], CFG))
        ws.assert_called_once_with("python latest")
        self.assertEqual(events, [("search", "python latest"), ("text", "It is 3.15.2."),
                                  ("sources", [("T", "https://t.example/")])])
        self.assertIn("tools", bodies[0])
        self.assertEqual(bodies[1]["messages"][-1], {"role": "tool", "tool_name": "web_search", "content": "RESULTS"})

    @override_settings(WEB_SEARCH_ENABLED=True)
    def test_tool_rounds_are_limited(self):
        call = {"function": {"name": "web_search", "arguments": '{"query": "again"}'}}
        bodies = []

        def fake_stream(cfg, body):
            bodies.append(body)
            return iter(chunks({"tool_calls": [call, call, call]}) if "tools" in body else chunks({"content": "done"}))

        with mock.patch.object(ollama, "_stream", side_effect=fake_stream), \
                mock.patch.object(websearch, "web_search", return_value=("R", [])) as ws:
            events = list(ollama.stream_chat([{"role": "user", "content": "q"}], CFG))
        self.assertEqual(len(bodies), ollama.MAX_TOOL_ROUNDS + 1)
        self.assertNotIn("tools", bodies[-1])
        self.assertEqual(ws.call_count, ollama.MAX_TOOL_ROUNDS * ollama.MAX_CALLS_PER_ROUND)
        self.assertEqual(events[-1], ("text", "done"))

    @override_settings(WEB_SEARCH_ENABLED=False)
    def test_disabled_search_sends_no_tools(self):
        with mock.patch.object(ollama, "_stream", return_value=iter(chunks({"content": "hi"}))) as stream:
            self.assertEqual(list(ollama.stream_chat([], CFG)), [("text", "hi")])
        self.assertNotIn("tools", stream.call_args.args[1])
        self.assertNotIn("web_search", ollama.system_prompt())

    @override_settings(WEB_SEARCH_ENABLED=False)
    def test_uses_dashboard_model_host_and_context(self):
        cfg = OllamaConfig(active_model="qwen3.5:latest", host="localhost:11500", context_length=16384, keep_alive="-1")
        with mock.patch.object(httpx, "stream") as stream:
            stream.return_value.__enter__.return_value = httpx.Response(
                200, content=b'{"message": {"content": "ok"}, "done": true}\n', request=httpx.Request("POST", "http://x"))
            self.assertEqual(list(ollama.stream_chat([], cfg)), [("text", "ok")])
        method, url = stream.call_args.args
        self.assertEqual(url, "http://127.0.0.1:11500/api/chat")
        body = stream.call_args.kwargs["json"]
        self.assertEqual(body["model"], "qwen3.5:latest")
        self.assertEqual(body["options"], {"num_ctx": 16384})
        self.assertEqual(body["keep_alive"], -1)

    def test_no_selected_model_is_an_error(self):
        with self.assertRaisesRegex(ollama.OllamaError, "No chat model"):
            list(ollama.stream_chat([], OllamaConfig(active_model="")))

    @override_settings(WEB_SEARCH_ENABLED=True)
    def test_model_without_tool_support_answers_without_search(self):
        bodies = []

        def fake_stream(cfg, body):
            bodies.append(dict(body))
            if "tools" in body:
                raise ollama.OllamaError("registry.ollama.ai/library/old does not support tools")
            return iter(chunks({"content": "plain answer"}))

        with mock.patch.object(ollama, "_stream", side_effect=fake_stream):
            events = list(ollama.stream_chat([{"role": "user", "content": "q"}], CFG))
        self.assertEqual(events, [("text", "plain answer")])
        self.assertEqual(["tools" in b for b in bodies], [True, False])

    def test_other_ollama_errors_are_not_swallowed(self):
        with mock.patch.object(ollama, "_stream", side_effect=ollama.OllamaError("model 'x' not found")):
            with self.assertRaisesRegex(ollama.OllamaError, "not found"):
                list(ollama.stream_chat([], CFG))


class MarkdownOutputTests(SimpleTestCase):
    def test_untrusted_text_cannot_inject_markdown(self):
        self.assertEqual(markdown_text("a [x](javascript:1) *b*\n<img>"), r"a \[x\](javascript:1) \*b\* \<img\>")

    def test_sources_only_allow_plain_http_urls(self):
        out = format_sources([("Good", "https://ok.example/a"), ("Bad", "javascript:alert(1)"), ("Sp", "https://x y")])
        self.assertIn("- [Good](<https://ok.example/a>)", out)
        self.assertNotIn("javascript", out)
        self.assertNotIn("x y", out)
        self.assertEqual(format_sources([]), "")


class ChatEndpointTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="u", password="some-password")
        self.client.force_authenticate(self.user)
        self.conv = Conversation.objects.create(user=self.user)
        cfg = OllamaConfig.load()
        cfg.active_model = "picked:model"
        cfg.save()

    def test_chat_model_endpoint_reports_dashboard_selection(self):
        self.assertEqual(self.client.get("/api/chat/model").data, {"model": "picked:model"})
        OllamaConfig.objects.update(active_model="")
        self.assertEqual(self.client.get("/api/chat/model").data, {"model": None})
        self.assertEqual(self.client_class().get("/api/chat/model").status_code, 401)

    def test_chat_without_selected_model_is_rejected_before_saving(self):
        OllamaConfig.objects.update(active_model="")
        response = self.client.post(f"/api/conversations/{self.conv.pk}/chat", {"content": "hi"}, format="json")
        self.assertEqual(response.status_code, 409)
        self.assertIn("No chat model", response.data["detail"])
        self.assertFalse(Message.objects.filter(conversation=self.conv).exists())

    def test_stream_saves_answer_and_sources_but_not_progress(self):
        events = [("search", "q"), ("text", "Answer."), ("sources", [("T", "https://t.example/")])]
        with mock.patch.object(ollama, "stream_chat", return_value=iter(events)) as stream_chat:
            response = self.client.post(f"/api/conversations/{self.conv.pk}/chat", {"content": "hi"}, format="json")
            body = b"".join(response.streaming_content).decode()
        self.assertEqual(stream_chat.call_args.args[1].active_model, "picked:model")
        self.assertIn("_Searching the web: q…_", body)
        saved = Message.objects.get(conversation=self.conv, role="assistant").content
        self.assertTrue(saved.startswith("Answer."))
        self.assertIn("[T](<https://t.example/>)", saved)
        self.assertNotIn("Searching", saved)

    def test_cannot_chat_in_another_users_conversation(self):
        other = Conversation.objects.create(user=User.objects.create_user(username="o", password="some-password"))
        response = self.client.post(f"/api/conversations/{other.pk}/chat", {"content": "hi"}, format="json")
        self.assertEqual(response.status_code, 404)
