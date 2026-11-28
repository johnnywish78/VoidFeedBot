"""AI readiness/status endpoint tests (no secrets returned)."""
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from _fixtures import prepare_workspace
_TMP = prepare_workspace("ai_status")
os.environ["TELEGRAM_BOT_TOKEN"] = "12345:fake-bot-token-ai"
os.environ["VOIDFEED_ADMIN_ID"] = "999000111"
os.environ["STUDIO_ADMIN_TOKEN"] = "ai-status-admin-token"
os.environ["VOIDFEED_DEMO"] = "0"
os.environ.pop("AI_API_BASE", None)
os.environ.pop("AI_API_KEY", None)
os.environ.pop("AI_MODEL", None)
os.environ.pop("AI_FALLBACK_MODELS", None)

from fastapi.testclient import TestClient  # noqa: E402

import studio  # noqa: E402

H = {"Authorization": "Bearer ai-status-admin-token"}


class AIStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_workspace("ai")

    def setUp(self):
        os.environ["STUDIO_ADMIN_TOKEN"] = "ai-status-admin-token"
        os.environ["VOIDFEED_ADMIN_ID"] = "999000111"
        os.environ["VOIDFEED_DEMO"] = "0"
        os.environ.pop("AI_API_BASE", None)
        os.environ.pop("AI_API_KEY", None)
        os.environ.pop("AI_MODEL", None)
        os.environ.pop("AI_FALLBACK_MODELS", None)
        self.client = TestClient(studio.app)
        self.h = {"Authorization": "Bearer ai-status-admin-token"}

    def test_status_requires_auth(self):
        self.assertEqual(self.client.get("/api/ai/status").status_code, 401)

    def test_status_unconfigured_no_secret(self):
        r = self.client.get("/api/ai/status", headers=self.h)
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertFalse(d["configured"])
        self.assertFalse(d["key_set"])
        self.assertFalse(d["ready"])
        self.assertEqual(d["base_host"], "")
        self.assertNotIn("sk-", str(d).lower())  # no secret value

    def test_status_configured_hostname_only(self):
        os.environ["AI_API_BASE"] = "https://inference.example.com/v1"
        os.environ["AI_API_KEY"] = "sk-SUPERSECRET"
        os.environ["AI_MODEL"] = "team/model-a"
        os.environ["AI_FALLBACK_MODELS"] = "org/model-b,org/model-c"
        r = self.client.get("/api/ai/status", headers=self.h).json()
        self.assertTrue(r["configured"])
        self.assertTrue(r["key_set"])
        self.assertEqual(r["base_host"], "inference.example.com")
        self.assertNotIn("inference.example.com/v1", r["base_host"])
        self.assertNotIn("SUPERSECRET", str(r))
        self.assertEqual(r["model"], "team/model-a")
        self.assertEqual(len(r["fallbacks"]), 2)

    def test_test_unconfigured_409(self):
        r = self.client.post("/api/ai/test", headers=self.h, json={})
        self.assertEqual(r.status_code, 409)

    def test_test_configured_ok(self):
        os.environ["AI_API_BASE"] = "https://ai.example.com/v1"
        os.environ["AI_API_KEY"] = "sk-secret-1"
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as m:
            m.return_value.status_code = 200
            r = self.client.post("/api/ai/test", headers=self.h, json={})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.assertNotIn("secret", str(r.json()))

    def test_test_configured_http_failure_sanitized(self):
        os.environ["AI_API_BASE"] = "https://ai.example.com/v1"
        os.environ["AI_API_KEY"] = "sk-secret-2"
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as m:
            m.return_value.status_code = 500
            r = self.client.post("/api/ai/test", headers=self.h, json={})
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertFalse(d["ok"])
        self.assertIn("500", d.get("error", ""))
        self.assertNotIn("secret", str(d).lower())


if __name__ == "__main__":
    unittest.main()
