import itertools
import json

import httpx
from django.conf import settings
from django.utils import timezone

from control.services import base_url

from . import websearch


class OllamaError(Exception):
    pass


WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the internet and read the top pages. Use it when the answer depends on current, "
            "recent or frequently changing information (news, prices, releases, versions, schedules, "
            "weather, sports, who currently holds a role) or on events after your training data."
        ),
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Short, specific search query"}},
            "required": ["query"],
        },
    },
}
MAX_TOOL_ROUNDS = 2       # model turns that may call tools before it must answer
MAX_CALLS_PER_ROUND = 2


def system_prompt():
    prompt = f"{settings.CHAT_SYSTEM_PROMPT}\n\nToday's date is {timezone.localdate().isoformat()}."
    if settings.WEB_SEARCH_ENABLED:
        prompt += (
            " You can call the web_search tool. Use it when the question needs up-to-date or time-sensitive "
            "information; otherwise answer directly without searching. When you use search results, base the "
            "answer on them, prefer the most recent sources, and say if the results don't answer the question."
        )
    return prompt


def _stream(cfg, body):
    """Yield parsed chunks from Ollama's streaming /api/chat."""
    try:
        with httpx.stream("POST", f"{base_url(cfg)}/api/chat", json=body,
                          timeout=httpx.Timeout(10.0, read=300.0)) as r:
            if r.status_code != 200:
                r.read()
                try:
                    detail = str(r.json().get("error") or "")[:300]
                except ValueError:
                    detail = ""
                raise OllamaError(detail or f"Ollama returned HTTP {r.status_code} for model '{body['model']}'.")
            for line in r.iter_lines():
                if not line:
                    continue
                data = json.loads(line)
                if "error" in data:
                    raise OllamaError(str(data["error"]))
                yield data
                if data.get("done"):
                    break
    except httpx.HTTPError as exc:
        raise OllamaError("Cannot reach Ollama") from exc


def _run_tool(call):
    """Execute one tool call. Returns (query or None, result text, sources)."""
    fn = call.get("function") or {}
    args = fn.get("arguments") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {}
    if fn.get("name") != "web_search" or not isinstance(args, dict):
        return None, f"Unknown tool '{fn.get('name')}'.", []
    query = " ".join(str(args.get("query", "")).split())[: websearch.MAX_QUERY]
    return query, *websearch.web_search(query)


def stream_chat(messages, cfg):
    """Chat with the model selected in the dashboard (`cfg` is the OllamaConfig).

    Yield ("text", chunk) for the answer, ("search", query) when a web search starts and
    ("sources", [(title, url), ...]) at the end if search results were used."""
    if not cfg.active_model:
        raise OllamaError("No chat model is selected. An admin can choose one in the Ollama dashboard.")
    messages = list(messages)
    sources = []
    tools = [WEB_SEARCH_TOOL] if settings.WEB_SEARCH_ENABLED else None
    for turn in range(MAX_TOOL_ROUNDS + 1):
        body = {"model": cfg.active_model, "messages": messages, "stream": True,
                "keep_alive": cfg.keep_alive_value(), "options": {"num_ctx": cfg.context_length}}
        if tools and turn < MAX_TOOL_ROUNDS:
            body["tools"] = tools
        text, calls = [], []
        try:
            chunks = _stream(cfg, body)
            first = next(chunks, None)  # HTTP errors surface here, before any output
        except OllamaError as exc:
            if "tools" not in body or "does not support tools" not in str(exc):
                raise
            tools = None  # the selected model can't call tools: answer without web search
            del body["tools"]
            chunks = _stream(cfg, body)
            first = next(chunks, None)
        for data in itertools.chain([first] if first else [], chunks):
            message = data.get("message", {})
            piece = message.get("content", "")
            if piece:
                text.append(piece)
                yield "text", piece
            calls += message.get("tool_calls") or []
        if not calls:
            break
        messages.append({"role": "assistant", "content": "".join(text), "tool_calls": calls})
        for n, call in enumerate(calls):
            name = (call.get("function") or {}).get("name", "")
            if n >= MAX_CALLS_PER_ROUND:
                messages.append({"role": "tool", "tool_name": name, "content": "Skipped: too many tool calls at once."})
                continue
            query, result, found = _run_tool(call)
            if query:
                yield "search", query
            sources += [s for s in found if s not in sources]
            messages.append({"role": "tool", "tool_name": name, "content": result})
    if sources:
        yield "sources", sources
