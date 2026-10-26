from unittest import mock

import httpx
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

from . import services

User = get_user_model()
AGENT = {"OLLAMA_AGENT_URL": "http://agent.test", "OLLAMA_AGENT_API_KEY": "test-key"}


def agent_response(status=200, body=None):
    return httpx.Response(status, json=body if body is not None else {})


@mock.patch.object(services, "_get", side_effect=httpx.ConnectError("no ollama"))
class OllamaControlTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="admin", password="admin-password", is_staff=True)
        self.client.force_authenticate(self.admin)

    def test_non_admin_is_forbidden(self, _get):
        self.client.force_authenticate(User.objects.create_user(username="u", password="some-password"))
        self.assertEqual(self.client.get("/api/admin/ollama/status").status_code, 403)

    @override_settings(OLLAMA_AGENT_API_KEY="")
    def test_status_reports_unconfigured_agent(self, _get):
        data = self.client.get("/api/admin/ollama/status").data
        self.assertFalse(data["agent_ok"])
        self.assertIn("OLLAMA_AGENT_API_KEY", data["agent_error"])
        self.assertEqual(self.client.post("/api/admin/ollama/start").status_code, 409)

    @override_settings(**AGENT)
    def test_start_sends_settings_with_api_key(self, _get):
        status = {"managed": True, "pid": 42, "binary_found": True}
        with mock.patch.object(httpx, "request", side_effect=[agent_response(), agent_response(body=status)]) as req:
            response = self.client.post("/api/admin/ollama/start")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["agent_ok"])
        self.assertEqual(response.data["pid"], 42)
        method, url = req.call_args_list[0].args
        self.assertEqual((method, url), ("POST", "http://agent.test/start"))
        kwargs = req.call_args_list[0].kwargs
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(kwargs["json"]["host"], "127.0.0.1:11434")

    @override_settings(**AGENT)
    def test_agent_errors_become_409(self, _get):
        with mock.patch.object(httpx, "request", return_value=agent_response(409, {"detail": "Ollama is not running."})):
            response = self.client.post("/api/admin/ollama/stop")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["detail"], "Ollama is not running.")
        with mock.patch.object(httpx, "request", return_value=agent_response(401)):
            response = self.client.get("/api/admin/ollama/logs")
        self.assertEqual(response.status_code, 409)
        self.assertIn("API key", response.data["detail"])
