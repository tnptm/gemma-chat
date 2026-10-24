import json

import httpx
from django.conf import settings


class OllamaError(Exception):
    pass


def stream_chat(messages):
    """Yield text chunks from the local Ollama server."""
    body = {"model": settings.OLLAMA_MODEL, "messages": messages, "stream": True}
    try:
        with httpx.stream("POST", f"{settings.OLLAMA_URL}/api/chat", json=body,
                          timeout=httpx.Timeout(10.0, read=300.0)) as r:
            if r.status_code != 200:
                r.read()
                raise OllamaError(f"Ollama returned HTTP {r.status_code} (is model '{settings.OLLAMA_MODEL}' pulled?)")
            for line in r.iter_lines():
                if not line:
                    continue
                data = json.loads(line)
                if "error" in data:
                    raise OllamaError(str(data["error"]))
                piece = data.get("message", {}).get("content", "")
                if piece:
                    yield piece
                if data.get("done"):
                    break
    except httpx.HTTPError as exc:
        raise OllamaError("Cannot reach Ollama") from exc
