import httpx
from django.conf import settings


class ServiceError(Exception):
    pass


def base_url(cfg):
    return "http://" + cfg.host.replace("localhost", "127.0.0.1")


def _get(cfg, path, timeout=3):
    r = httpx.get(base_url(cfg) + path, timeout=timeout)
    r.raise_for_status()
    return r.json()


# --- Control agent (ollama-agent/, runs on the host and owns the Ollama process) ---

def _agent(method, path, timeout=5.0, **kwargs):
    if not settings.OLLAMA_AGENT_API_KEY:
        raise ServiceError("The Ollama control agent is not configured. Set OLLAMA_AGENT_API_KEY in backend/.env.")
    try:
        r = httpx.request(method, settings.OLLAMA_AGENT_URL + path, timeout=timeout,
                          headers={"Authorization": f"Bearer {settings.OLLAMA_AGENT_API_KEY}"}, **kwargs)
    except httpx.HTTPError as exc:
        raise ServiceError("Cannot reach the Ollama control agent. Is ollama-agent running?") from exc
    if r.status_code == 401:
        raise ServiceError("The Ollama control agent rejected the API key.")
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code != 200:
        raise ServiceError(data.get("detail") or f"Control agent returned HTTP {r.status_code}.")
    return data


def status(cfg):
    info = {
        "running": False, "managed": False, "pid": None, "version": None, "binary_found": False,
        "agent_ok": False, "agent_error": None, "installed": [], "loaded": [],
    }
    try:
        agent = _agent("GET", "/status", timeout=3.0)
        info.update(agent_ok=True, managed=agent["managed"], pid=agent["pid"], binary_found=agent["binary_found"])
    except (ServiceError, KeyError) as exc:
        info["agent_error"] = str(exc) if isinstance(exc, ServiceError) else "Unexpected control agent response."
    try:
        info["version"] = _get(cfg, "/api/version")["version"]
        info["running"] = True
        info["installed"] = [{"name": m["name"], "size": m.get("size", 0)} for m in _get(cfg, "/api/tags").get("models", [])]
        info["loaded"] = [
            {"name": m["name"], "size": m.get("size", 0), "size_vram": m.get("size_vram", 0), "expires_at": m.get("expires_at")}
            for m in _get(cfg, "/api/ps").get("models", [])
        ]
    except (httpx.HTTPError, ValueError, KeyError):
        pass
    return info


def start(cfg):
    _agent("POST", "/start", timeout=30.0, json=cfg.server_settings())


def stop(cfg):
    _agent("POST", "/stop", timeout=20.0)


def restart(cfg):
    _agent("POST", "/restart", timeout=45.0, json=cfg.server_settings())


def set_loaded(cfg, model, load):
    st = status(cfg)
    if not st["running"]:
        raise ServiceError("Ollama is not running.")
    if model not in {m["name"] for m in st["installed"]}:
        raise ServiceError("Unknown model.")
    body = {"model": model, "keep_alive": cfg.keep_alive_value() if load else 0}
    try:
        r = httpx.post(base_url(cfg) + "/api/generate", json=body, timeout=httpx.Timeout(10.0, read=300.0))
        r.raise_for_status()
    except httpx.HTTPError as exc:
        raise ServiceError(f"Ollama error: {exc}") from exc


def log_tail(lines=200):
    return _agent("GET", "/logs", params={"lines": lines})["lines"]
