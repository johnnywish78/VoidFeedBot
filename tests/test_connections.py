"""Connection Center tests — provider architecture, OAuth security, disconnect.

Runs against the real FastAPI app (studio) with an isolated WORK_DIR and fake
env config. No network: the token-exchange path is exercised with a mocked
httpx.AsyncClient.post.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from _fixtures import prepare_workspace
_TMP = prepare_workspace("conn")
os.environ["TELEGRAM_BOT_TOKEN"] = "12345:fake-bot-token-for-conn-tests"
os.environ["VOIDFEED_ADMIN_ID"] = "999000111"
os.environ["STUDIO_ADMIN_TOKEN"] = "conn-test-admin-token"
os.environ["VOIDFEED_DEMO"] = "0"
# fake dev creds for instagram so "configured" path can be tested
os.environ["INSTAGRAM_CLIENT_ID"] = "fake_ig_id"
os.environ["INSTAGRAM_CLIENT_SECRET"] = "fake_ig_secret"
os.environ["INSTAGRAM_REDIRECT_URI"] = "http://localhost:8077/api/connections/instagram/callback"
os.environ["STUDIO_TOKEN_ENCRYPTION_KEY"] = "a" * 64  # 32-byte hex key

from fastapi.testclient import TestClient  # noqa: E402

import studio  # noqa: E402
import voidfeed_db as db  # noqa: E402


class ConnectionCenterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_workspace("conn")

    def setUp(self):
        # Re-assert env each test so import order by other modules (e.g.
        # test_studio_api clobbering env at its import) cannot break us.
        os.environ["STUDIO_ADMIN_TOKEN"] = "conn-test-admin-token"
        os.environ["VOIDFEED_ADMIN_ID"] = "999000111"
        os.environ["VOIDFEED_DEMO"] = "0"
        os.environ["INSTAGRAM_CLIENT_ID"] = "fake_ig_id"
        os.environ["INSTAGRAM_CLIENT_SECRET"] = "fake_ig_secret"
        os.environ["INSTAGRAM_REDIRECT_URI"] = "http://localhost:8077/api/connections/instagram/callback"
        os.environ["STUDIO_TOKEN_ENCRYPTION_KEY"] = "a" * 64
        self.admin_h = {"Authorization": "Bearer conn-test-admin-token"}
        self.client = TestClient(studio.app)

    def test_provider_registry_has_all_six(self):
        import providers
        self.assertEqual(set(providers.PROVIDERS.keys()),
                        {"telegram", "instagram", "facebook",
                         "youtube", "x", "tiktok"})

    def test_connections_endpoint_lists_all_providers(self):
        r = self.client.get("/api/connections", headers=self.admin_h)
        self.assertEqual(r.status_code, 200)
        keys = [p["key"] for p in r.json()]
        self.assertEqual(keys, ["telegram", "instagram", "facebook",
                                "youtube", "x", "tiktok"])
        # no token-like fields leak
        for p in r.json():
            for c in p.get("connections", []):
                self.assertNotIn("token_encrypted", c)
                self.assertNotIn("refresh_token_encrypted", c)

    def test_telegram_reported_configured_with_bot_token(self):
        r = self.client.get("/api/connections", headers=self.admin_h).json()
        tg = next(p for p in r if p["key"] == "telegram")
        self.assertEqual(tg["status"], "configured")
        self.assertTrue(tg["publish_available"])
        # registered channels appear under its connections
        cid = db.add_channel(-1001, "Test Channel", "testchan")
        try:
            r2 = self.client.get("/api/connections", headers=self.admin_h).json()
            tg2 = next(p for p in r2 if p["key"] == "telegram")
            self.assertEqual(len(tg2["connections"]), 1)
            self.assertEqual(tg2["connections"][0]["title"], "Test Channel")
        finally:
            db.remove_channel(cid)

    def test_awaiting_setup_when_creds_missing(self):
        # Facebook has no fake creds set -> awaiting_setup
        r = self.client.get("/api/connections", headers=self.admin_h).json()
        fb = next(p for p in r if p["key"] == "facebook")
        self.assertEqual(fb["status"], "awaiting_setup")
        self.assertIn("FACEBOOK_APP_ID", fb["missing_env"])
        self.assertIn("FACEBOOK_APP_SECRET", fb["missing_env"])
        # publish must be false
        self.assertFalse(fb["publish_available"])

    def test_authorize_rejected_for_unconfigured_provider(self):
        r = self.client.post("/api/connections/facebook/authorize",
                             headers=self.admin_h)
        self.assertEqual(r.status_code, 409)
        self.assertIn("FACEBOOK_APP_ID", r.json()["detail"]["missing_env"])

    def test_authorize_requires_auth(self):
        r = self.client.post("/api/connections/instagram/authorize")
        self.assertEqual(r.status_code, 401)

    def test_authorize_telegram_not_oauth(self):
        r = self.client.post("/api/connections/telegram/authorize",
                             headers=self.admin_h)
        self.assertEqual(r.status_code, 400)

    def test_authorize_returns_url_with_state_when_configured(self):
        r = self.client.post("/api/connections/instagram/authorize",
                             headers=self.admin_h)
        self.assertEqual(r.status_code, 200)
        url = r.json()["authorize_url"]
        self.assertIn("client_id=fake_ig_id", url)
        self.assertIn("state=", url)
        self.assertIn("redirect_uri=", url)

    def test_callback_invalid_state_rejected(self):
        r = self.client.get(
            "/api/connections/instagram/callback",
            params={"code": "x", "state": "bogus-state"})
        self.assertEqual(r.status_code, 400)

    def test_callback_missing_state_rejected(self):
        r = self.client.get(
            "/api/connections/instagram/callback",
            params={"code": "x"})
        self.assertEqual(r.status_code, 400)

    def test_callback_error_param_rejected(self):
        # first set a valid state so the only failure is the error param
        self.client.post("/api/connections/instagram/authorize",
                         headers=self.admin_h)
        r = self.client.get(
            "/api/connections/instagram/callback",
            params={"code": "x", "state": "whatever", "error": "access_denied"})
        self.assertEqual(r.status_code, 400)

    def test_callback_expired_state_rejected(self):
        self.client.post("/api/connections/instagram/authorize",
                         headers=self.admin_h)
        db.set_setting("oauth_state:instagram", json.dumps(
            {"state": "s1", "exp": 0}))  # already expired
        r = self.client.get(
            "/api/connections/instagram/callback",
            params={"code": "x", "state": "s1"})
        self.assertEqual(r.status_code, 400)

    def test_callback_success_saves_encrypted_token(self):
        self.client.post("/api/connections/instagram/authorize",
                         headers=self.admin_h)
        raw = json.loads(db.get_setting("oauth_state:instagram"))
        state = raw["state"]
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as m:
            m.return_value.status_code = 200
            m.return_value.json = lambda: {
                "access_token": "SECRET_ACCESS_1234",
                "refresh_token": "SECRET_REFRESH_5678",
                "expires_in": 3600,
                "user_id": "ig_user_1",
            }
            r = self.client.get(
                "/api/connections/instagram/callback",
                params={"code": "c1", "state": state})
        self.assertEqual(r.status_code, 200)
        conns = db.list_connections("instagram")
        self.assertEqual(len(conns), 1)
        row = conns[0]
        self.assertEqual(row["status"], "connected")
        # tokens stored encrypted (not plaintext)
        self.assertNotIn("SECRET_ACCESS_1234", row["token_encrypted"])
        self.assertNotIn("SECRET_REFRESH_5678", row["refresh_token_encrypted"])
        # single-use state consumed
        self.assertFalse(db.get_setting("oauth_state:instagram"))

    def test_disconnect_removes_connection(self):
        cid = db.save_connection("instagram", account_id="u1",
                                 account_name="Acct",
                                 token_encrypted="enc", status="connected")
        r = self.client.post(f"/api/connections/{cid}/disconnect",
                             headers=self.admin_h)
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(db.get_connection(cid))

    def test_disconnect_requires_auth(self):
        r = self.client.post("/api/connections/999/disconnect")
        self.assertEqual(r.status_code, 401)

    def test_disconnect_missing_404(self):
        r = self.client.post("/api/connections/424242/disconnect",
                             headers=self.admin_h)
        self.assertEqual(r.status_code, 404)

    def test_token_redaction_in_logs(self):
        # ensure the exchange path logs nothing containing the token.
        # We assert by running a callback and checking the log buffer.
        import io
        import logging
        buf = io.StringIO()
        h = logging.StreamHandler(buf)
        logger = logging.getLogger("VoidFeedStudio")
        logger.addHandler(h)
        try:
            self.client.post("/api/connections/instagram/authorize",
                             headers=self.admin_h)
            raw = json.loads(db.get_setting("oauth_state:instagram"))
            with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as m:
                m.return_value.status_code = 200
                m.return_value.json = lambda: {
                    "access_token": "TOPSECRET_ZZ", "user_id": "u9"}
                self.client.get("/api/connections/instagram/callback",
                                params={"code": "c", "state": raw["state"]})
            logs = buf.getvalue()
            self.assertNotIn("TOPSECRET_ZZ", logs)
        finally:
            logger.removeHandler(h)


if __name__ == "__main__":
    unittest.main()
