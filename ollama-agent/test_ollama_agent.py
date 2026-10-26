"""Run with: uv run python -m unittest discover -s ollama-agent"""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import ollama_agent as agent

KEY = "k" * 40


class AgentApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        run = Path(cls.tmp.name)
        cls.patches = {"API_KEY": KEY, "RUN_DIR": run, "STATE_FILE": run / "ollama.json",
                       "LOG_FILE": run / "ollama.log", "OLLAMA_BIN": "definitely-not-ollama"}
        cls.saved = {k: getattr(agent, k) for k in cls.patches}
        for k, v in cls.patches.items():
            setattr(agent, k, v)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), agent.Handler)
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        for k, v in cls.saved.items():
            setattr(agent, k, v)
        cls.tmp.cleanup()

    def call(self, method, path, body=None, key=KEY):
        headers = {"Authorization": f"Bearer {key}"} if key is not None else {}
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.url + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read() or b"null")

    def test_requires_valid_api_key(self):
        self.assertEqual(self.call("GET", "/status", key=None)[0], 401)
        self.assertEqual(self.call("GET", "/status", key="wrong")[0], 401)
        self.assertEqual(self.call("POST", "/stop", key="wrong")[0], 401)

    def test_status(self):
        code, body = self.call("GET", "/status")
        self.assertEqual(code, 200)
        self.assertEqual(body["managed"], False)
        self.assertEqual(body["binary_found"], False)

    def test_start_validates_settings(self):
        bad = [
            {"host": "0.0.0.0:11434"},
            {"host": "example.com:11434"},
            {"context_length": 100},
            {"num_parallel": True},
            {"keep_alive": "5m; rm -rf /"},
            {"models_dir": "relative/path"},
            {"unknown": 1},
            [],
        ]
        for body in bad:
            with self.subTest(body=body):
                self.assertEqual(self.call("POST", "/start", body)[0], 400)

    def test_start_without_binary_and_stop_without_process(self):
        code, body = self.call("POST", "/start", {"host": "127.0.0.1:19"})
        self.assertEqual(code, 409)
        self.assertIn("not found", body["detail"])
        self.assertEqual(self.call("POST", "/stop")[0], 409)

    def test_logs_and_unknown_routes(self):
        self.assertEqual(self.call("GET", "/logs?lines=5"), (200, {"lines": ""}))
        self.assertEqual(self.call("GET", "/nope")[0], 404)
        self.assertEqual(self.call("GET", "/start")[0], 405)

    def test_child_env_drops_agent_secrets(self):
        agent.os.environ["OLLAMA_AGENT_API_KEY"] = KEY
        try:
            env = agent.ollama_env(agent.validate_config({"models_dir": "/tmp"}))
        finally:
            del agent.os.environ["OLLAMA_AGENT_API_KEY"]
        self.assertNotIn("OLLAMA_AGENT_API_KEY", env)
        self.assertEqual(env["OLLAMA_MODELS"], "/tmp")
        self.assertEqual(env["OLLAMA_HOST"], "127.0.0.1:11434")


if __name__ == "__main__":
    unittest.main()
