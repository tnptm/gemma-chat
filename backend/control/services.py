import os
import shutil
import subprocess
import time

import httpx
import psutil
from django.conf import settings

RUN_DIR = settings.BASE_DIR / "run"
PID_FILE = RUN_DIR / "ollama.pid"
LOG_FILE = RUN_DIR / "ollama.log"

# Keep the app's own secrets out of the Ollama process
_STRIP_PREFIXES = ("DJANGO_", "CSRF_", "COOKIE_", "CHAT_", "OLLAMA_")


class ServiceError(Exception):
    pass


def base_url(cfg):
    return "http://" + cfg.host.replace("localhost", "127.0.0.1")


def _get(cfg, path, timeout=3):
    r = httpx.get(base_url(cfg) + path, timeout=timeout)
    r.raise_for_status()
    return r.json()


def managed_process():
    """The ollama process this dashboard started. The pid file also stores the process
    start time, so a recycled PID that belongs to some other program is never touched."""
    try:
        pid, started = PID_FILE.read_text().split(":")
        proc = psutil.Process(int(pid))
        if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE and abs(proc.create_time() - float(started)) < 1:
            return proc
    except (OSError, ValueError, psutil.Error):
        pass
    PID_FILE.unlink(missing_ok=True)
    return None


def status(cfg):
    proc = managed_process()
    info = {
        "running": False, "managed": proc is not None, "pid": proc.pid if proc else None,
        "version": None, "binary_found": shutil.which(settings.OLLAMA_BIN) is not None,
        "installed": [], "loaded": [],
    }
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
    if status(cfg)["running"]:
        raise ServiceError("Ollama is already running.")
    binary = shutil.which(settings.OLLAMA_BIN)
    if not binary:
        raise ServiceError(f"Executable '{settings.OLLAMA_BIN}' not found. Set OLLAMA_BIN in backend/.env.")
    RUN_DIR.mkdir(exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(_STRIP_PREFIXES)}
    env.update(cfg.env())
    extra = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    with open(LOG_FILE, "ab") as log:
        proc = subprocess.Popen([binary, "serve"], env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log, **extra)
    PID_FILE.write_text(f"{proc.pid}:{psutil.Process(proc.pid).create_time()}")
    for _ in range(40):  # up to ~20 s
        if status(cfg)["running"]:
            return
        if proc.poll() is not None:
            PID_FILE.unlink(missing_ok=True)
            raise ServiceError("Ollama exited right after starting. Check the log.")
        time.sleep(0.5)
    raise ServiceError("Ollama did not become ready in time. Check the log.")


def stop(cfg):
    proc = managed_process()
    if not proc:
        if status(cfg)["running"]:
            raise ServiceError("This Ollama was not started from the dashboard (e.g. a system service), so it can't be stopped here.")
        raise ServiceError("Ollama is not running.")
    tree = [proc] + proc.children(recursive=True)  # includes model runner processes
    for p in tree:
        try:
            p.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(tree, timeout=10)
    for p in alive:
        try:
            p.kill()
        except psutil.Error:
            pass
    PID_FILE.unlink(missing_ok=True)


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
    try:
        with open(LOG_FILE, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 65536))
            return "\n".join(f.read().decode("utf-8", "replace").splitlines()[-lines:])
    except OSError:
        return ""
