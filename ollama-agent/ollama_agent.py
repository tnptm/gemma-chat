"""Ollama control agent: starts and stops a local `ollama serve` with explicit settings.

Runs on the host (outside Docker), so the containerised Django app, or any other
program or `curl`, can manage the host's Ollama process. The JSON API listens on
loopback only, and every request must send `Authorization: Bearer <OLLAMA_AGENT_API_KEY>`.

    uv run python ollama-agent/ollama_agent.py
"""
import hmac
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import psutil
from dotenv import load_dotenv

AGENT_DIR = Path(__file__).resolve().parent
load_dotenv(AGENT_DIR / ".env")

API_KEY = os.environ.get("OLLAMA_AGENT_API_KEY", "")
BIND = os.environ.get("OLLAMA_AGENT_BIND", "127.0.0.1:11435")
OLLAMA_BIN = os.environ.get("OLLAMA_BIN", "ollama")
RUN_DIR = Path(os.environ.get("OLLAMA_AGENT_RUN_DIR") or AGENT_DIR / "run")
STATE_FILE = RUN_DIR / "ollama.json"
LOG_FILE = RUN_DIR / "ollama.log"

MIN_KEY_LENGTH = 32
MAX_BODY = 16 * 1024
# Keep the agent's own secrets (and other apps' settings) out of the Ollama process
STRIP_PREFIXES = ("OLLAMA_", "DJANGO_", "CSRF_", "COOKIE_", "CHAT_")

LOOPBACK_HOST = re.compile(r"^(127\.0\.0\.1|localhost|\[::1\]):(\d{2,5})$")
KEEP_ALIVE = re.compile(r"^(-1|\d+[smh]?)$")

DEFAULTS = {
    "host": "127.0.0.1:11434",
    "context_length": 8192,
    "keep_alive": "5m",
    "num_parallel": 1,
    "max_loaded_models": 1,
    "flash_attention": False,
    "models_dir": "",
}
INT_RANGES = {"context_length": (512, 262144), "num_parallel": (1, 8), "max_loaded_models": (1, 4)}

log = logging.getLogger("ollama-agent")
lock = threading.Lock()  # one start/stop at a time


class AgentError(Exception):
    def __init__(self, detail, status=409):
        super().__init__(detail)
        self.detail, self.status = detail, status


# --- Validation ---

def validate_config(data):
    """Return a complete, validated Ollama config. Unknown keys are rejected."""
    if not isinstance(data, dict):
        raise AgentError("Expected a JSON object.", 400)
    unknown = set(data) - set(DEFAULTS)
    if unknown:
        raise AgentError(f"Unknown setting(s): {', '.join(sorted(unknown))}.", 400)
    cfg = {**DEFAULTS, **data}
    host = isinstance(cfg["host"], str) and LOOPBACK_HOST.fullmatch(cfg["host"])
    if not host or not 1 <= int(host.group(2)) <= 65535:
        raise AgentError("host must be a loopback address with port, e.g. 127.0.0.1:11434.", 400)
    for key, (low, high) in INT_RANGES.items():
        value = cfg[key]
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise AgentError(f"{key} must be an integer between {low} and {high}.", 400)
    if not isinstance(cfg["keep_alive"], str) or not KEEP_ALIVE.fullmatch(cfg["keep_alive"]):
        raise AgentError("keep_alive must look like 5m, 30s, 1h, 0 or -1.", 400)
    if not isinstance(cfg["flash_attention"], bool):
        raise AgentError("flash_attention must be true or false.", 400)
    models_dir = cfg["models_dir"]
    if not isinstance(models_dir, str) or len(models_dir) > 500 or "\0" in models_dir \
            or (models_dir and not Path(models_dir).is_absolute()):
        raise AgentError("models_dir must be empty or an absolute path.", 400)
    return cfg


def ollama_env(cfg):
    env = {k: v for k, v in os.environ.items() if not k.startswith(STRIP_PREFIXES)}
    env.update({
        "OLLAMA_HOST": cfg["host"],
        "OLLAMA_CONTEXT_LENGTH": str(cfg["context_length"]),
        "OLLAMA_KEEP_ALIVE": cfg["keep_alive"],
        "OLLAMA_NUM_PARALLEL": str(cfg["num_parallel"]),
        "OLLAMA_MAX_LOADED_MODELS": str(cfg["max_loaded_models"]),
        "OLLAMA_FLASH_ATTENTION": "1" if cfg["flash_attention"] else "0",
    })
    if cfg["models_dir"]:
        env["OLLAMA_MODELS"] = cfg["models_dir"]
    return env


# --- Process management ---

def api_ready(host):
    url = "http://" + host.replace("localhost", "127.0.0.1") + "/api/version"
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def read_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return None


def managed_process():
    """The ollama process this agent started. The state file also stores the process
    start time, so a recycled PID that belongs to some other program is never touched."""
    state = read_state()
    try:
        proc = psutil.Process(int(state["pid"]))
        if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE \
                and abs(proc.create_time() - float(state["started"])) < 1:
            return proc, state
    except (TypeError, KeyError, ValueError, psutil.Error):
        pass
    STATE_FILE.unlink(missing_ok=True)
    return None, None


def status():
    proc, state = managed_process()
    host = state["host"] if state else None
    return {
        "managed": proc is not None,
        "pid": proc.pid if proc else None,
        "host": host,
        "ready": bool(host and api_ready(host)),
        "binary_found": shutil.which(OLLAMA_BIN) is not None,
    }


def start(cfg):
    if managed_process()[0]:
        raise AgentError("Ollama is already running (started by this agent).")
    if api_ready(cfg["host"]):
        raise AgentError(f"Something is already serving Ollama on {cfg['host']} (not started by this agent).")
    binary = shutil.which(OLLAMA_BIN)
    if not binary:
        raise AgentError(f"Executable '{OLLAMA_BIN}' not found. Set OLLAMA_BIN in ollama-agent/.env.")
    if cfg["models_dir"] and not Path(cfg["models_dir"]).is_dir():
        raise AgentError("models_dir does not exist on the host.")
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    extra = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    with open(LOG_FILE, "ab") as out:
        proc = subprocess.Popen([binary, "serve"], env=ollama_env(cfg), stdin=subprocess.DEVNULL,
                                stdout=out, stderr=out, **extra)
    STATE_FILE.write_text(json.dumps({"pid": proc.pid, "started": psutil.Process(proc.pid).create_time(),
                                      "host": cfg["host"]}))
    log.info("started ollama pid=%s host=%s", proc.pid, cfg["host"])
    for _ in range(40):  # up to ~20 s
        if api_ready(cfg["host"]):
            return
        if proc.poll() is not None:
            STATE_FILE.unlink(missing_ok=True)
            raise AgentError("Ollama exited right after starting. Check the log.")
        time.sleep(0.5)
    raise AgentError("Ollama did not become ready in time. Check the log.")


def stop():
    proc, _ = managed_process()
    if not proc:
        raise AgentError("Ollama is not running (or was not started by this agent).")
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
    STATE_FILE.unlink(missing_ok=True)
    log.info("stopped ollama pid=%s", proc.pid)


def log_tail(lines=200):
    try:
        with open(LOG_FILE, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 65536))
            return "\n".join(f.read().decode("utf-8", "replace").splitlines()[-lines:])
    except OSError:
        return ""


# --- HTTP API ---

class Handler(BaseHTTPRequestHandler):
    server_version = "ollama-agent"
    sys_version = ""

    def _send(self, code, body=None):
        data = b"" if body is None else json.dumps(body).encode()
        self.send_response(code)
        if code == 401:
            self.send_header("WWW-Authenticate", "Bearer")
        if body is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self):
        header = self.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        return scheme.lower() == "bearer" and hmac.compare_digest(token.strip().encode(), API_KEY.encode())

    def _body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise AgentError("Invalid Content-Length.", 400)
        if length > MAX_BODY:
            raise AgentError("Request body too large.", 413)
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw) if raw.strip() else {}
        except ValueError:
            raise AgentError("Body must be JSON.", 400)

    def _dispatch(self, method):
        if not self._authorized():
            log.warning("rejected unauthorised %s %s", method, self.path)
            return self._send(401, {"detail": "Missing or invalid API key."})
        url = urlsplit(self.path)
        try:
            if method == "GET" and url.path == "/status":
                return self._send(200, status())
            if method == "GET" and url.path == "/logs":
                try:
                    lines = int(parse_qs(url.query).get("lines", ["200"])[0])
                except ValueError:
                    raise AgentError("lines must be an integer.", 400)
                return self._send(200, {"lines": log_tail(max(1, min(lines, 1000)))})
            if method == "POST" and url.path in ("/start", "/restart"):
                cfg = validate_config(self._body())
                with lock:
                    if url.path == "/restart" and managed_process()[0]:
                        stop()
                    start(cfg)
                return self._send(200, status())
            if method == "POST" and url.path == "/stop":
                with lock:
                    stop()
                return self._send(200, status())
            if url.path in ("/status", "/logs", "/start", "/restart", "/stop"):
                return self._send(405, {"detail": "Method not allowed."})
            return self._send(404, {"detail": "Not found."})
        except AgentError as exc:
            return self._send(exc.status, {"detail": exc.detail})
        except Exception:
            log.exception("request failed")
            return self._send(500, {"detail": "Internal error. See the agent log."})

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def log_message(self, fmt, *args):
        log.info("%s %s", self.address_string(), fmt % args)


def parse_bind(value):
    match = LOOPBACK_HOST.fullmatch(value)
    if not match or not 1 <= int(match.group(2)) <= 65535:
        raise SystemExit("OLLAMA_AGENT_BIND must be a loopback address with port, e.g. 127.0.0.1:11435.")
    return match.group(1).strip("[]"), int(match.group(2))


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if len(API_KEY) < MIN_KEY_LENGTH:
        raise SystemExit(f"Set OLLAMA_AGENT_API_KEY (at least {MIN_KEY_LENGTH} characters) in ollama-agent/.env.")
    host, port = parse_bind(BIND)
    server_cls = type("Server", (ThreadingHTTPServer,), {"address_family": socket.AF_INET6}) \
        if ":" in host else ThreadingHTTPServer
    server = server_cls((host, port), Handler)
    log.info("listening on http://%s (ollama binary: %s)", BIND, shutil.which(OLLAMA_BIN) or "NOT FOUND")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
