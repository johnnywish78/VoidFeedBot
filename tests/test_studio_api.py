"""Studio API tests — auth, media access control, network variants.

Runs against the real FastAPI app with an isolated WORK_DIR (temp SQLite +
media dir) and a FAKE bot token. The initData used here is computed locally
with that fake token, so no production credential is ever touched.

Run: WORK_DIR-independent:  python -m unittest tests.test_studio_api -v
"""
import hashlib
import hmac
import json
import os
import shutil
import tempfile
import time
import unittest
import urllib.parse
from pathlib import Path

# Isolation must happen BEFORE studio/voidfeed_db are imported.
from _fixtures import prepare_workspace
_TMP = prepare_workspace("studio_api")
os.environ["TELEGRAM_BOT_TOKEN"] = "12345:fake-token-for-clone-tests-only"
os.environ["VOIDFEED_ADMIN_ID"] = "999000111"
os.environ["STUDIO_ADMIN_TOKEN"] = "clone-test-admin-token"  # throwaway test token
os.environ.pop("VOIDFEED_DEMO", None)  # production auth semantics

from fastapi.testclient import TestClient  # noqa: E402

import studio  # noqa: E402  (imports voidfeed_db with WORK_DIR set)
import voidfeed_db as db  # noqa: E402

ADMIN_ID = 999000111
FAKE_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

# 1x1 transparent PNG (not a secret, standard test fixture)
PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c626001000000ffff03000006000557bfabd40000000049454e44ae426082"
)


def make_init_data(user_id: int = ADMIN_ID, auth_date: float | None = None,
                   token: str = FAKE_TOKEN) -> str:
    """Build initData exactly the way validate_init_data expects."""
    pairs = {
        "auth_date": str(int(auth_date if auth_date is not None else time.time())),
        "query_id": "AAtestquery",
        "user": json.dumps({"id": user_id, "first_name": "Tester"},
                           separators=(",", ":")),
    }
    raw = "&".join(f"{k}={urllib.parse.quote(v, safe='')}"
                   for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    check_string = "\n".join(f"{k}={urllib.parse.unquote(v)}"
                             for k, v in sorted(pairs.items()))
    sig = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return f"{raw}&hash={sig}"


AUTH = {"Authorization": "tma " + make_init_data()}


class StudioApiTests(unittest.TestCase):
    def setUp(self):
        # Re-assert our env (other modules like test_connections clobber env
        # at import/setUp; restoring here keeps tests order-independent).
        os.environ["STUDIO_ADMIN_TOKEN"] = "clone-test-admin-token"
        os.environ["VOIDFEED_ADMIN_ID"] = "999000111"
        os.environ["VOIDFEED_DEMO"] = ""
        os.environ["TELEGRAM_BOT_TOKEN"] = "12345:fake-token-for-clone-tests-only"
        self.bearer = {"Authorization": "Bearer clone-test-admin-token"}

    @classmethod
    def setUpClass(cls):
        prepare_workspace("studio")  # re-pin this module's DB before tests
        cls.client = TestClient(studio.app)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_TMP, ignore_errors=True)

    # ---------------- authentication ----------------

    def test_me_requires_auth(self):
        r = self.client.get("/api/me")
        self.assertEqual(r.status_code, 401)
        r = self.client.get("/api/me", headers={"Authorization": "Bearer junk"})
        self.assertEqual(r.status_code, 401)
        r = self.client.get("/api/me", headers={"Authorization": "tma garbage"})
        self.assertEqual(r.status_code, 401)

    def test_me_rejects_expired_init_data(self):
        stale = make_init_data(auth_date=time.time() - 86401)
        r = self.client.get("/api/me", headers={"Authorization": "tma " + stale})
        self.assertEqual(r.status_code, 401)

    def test_me_rejects_non_admin_user(self):
        other = make_init_data(user_id=111222333)
        r = self.client.get("/api/me", headers={"Authorization": "tma " + other})
        self.assertEqual(r.status_code, 403)

    def test_me_accepts_valid_admin(self):
        r = self.client.get("/api/me", headers=AUTH)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["user"]["id"], ADMIN_ID)

    def test_tampered_init_data_rejected(self):
        raw = make_init_data()
        r = self.client.get("/api/me",
                            headers={"Authorization": "tma " + raw[:-4] + "beef"})
        self.assertEqual(r.status_code, 401)

    # ---------------- media access control (Phase 1 regression) ----------------

    def _upload_png(self):
        r = self.client.post("/api/media", headers=AUTH,
                             files={"file": ("t.png", PNG_1X1, "image/png")})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_media_upload_and_authenticated_retrieval(self):
        up = self._upload_png()
        url = up["url"]
        self.assertTrue(url.startswith("/media/"))
        got = self.client.get(url, headers=AUTH)
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.content, PNG_1X1)

    def test_media_requires_auth(self):
        up = self._upload_png()
        self.assertEqual(self.client.get(up["url"]).status_code, 401)
        bad = self.client.get(up["url"], headers={"Authorization": "Bearer junk"})
        self.assertEqual(bad.status_code, 401)
        # valid initData for a NON-admin must also be denied
        other = {"Authorization": "tma " + make_init_data(user_id=111222333)}
        self.assertEqual(self.client.get(up["url"], headers=other).status_code, 403)

    def test_media_missing_file_404(self):
        r = self.client.get("/media/does_not_exist_000.png", headers=AUTH)
        self.assertEqual(r.status_code, 404)

    def test_media_traversal_rejected(self):
        r = self.client.get("/media/..%2F..%2Fetc%2Fpasswd", headers=AUTH)
        self.assertIn(r.status_code, (400, 404))
        self.assertNotIn(b"root:", r.content)

    def test_media_bad_extension_rejected(self):
        r = self.client.post("/api/media", headers=AUTH,
                             files={"file": ("evil.svg", b"<svg/>", "image/svg+xml")})
        self.assertEqual(r.status_code, 400)

    # ---------------- network variants (Phase 3 persistence) ----------------

    def test_variants_persist_and_roundtrip(self):
        variants = {"x": "short post for X", "instagram": "IG caption with #tag"}
        r = self.client.post("/api/drafts", headers=AUTH,
                             json={"content": "main text", "variants": variants})
        self.assertEqual(r.status_code, 200, r.text)
        did = r.json()["id"]
        self.assertEqual(r.json().get("variants"), variants)
        got = self.client.get(f"/api/drafts/{did}", headers=AUTH).json()
        self.assertEqual(got["variants"], variants)
        # retrieval through the list endpoint as well
        listed = self.client.get("/api/drafts", headers=AUTH).json()
        match = [d for d in listed if d["id"] == did]
        self.assertTrue(match and match[0]["variants"] == variants)

    def test_variants_update_and_clear(self):
        did = self.client.post("/api/drafts", headers=AUTH,
                               json={"content": "hello", "variants": {"x": "v1"}}).json()["id"]
        r = self.client.put(f"/api/drafts/{did}", headers=AUTH,
                            json={"variants": {"x": "v2", "tiktok": "tt"}})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["variants"], {"x": "v2", "tiktok": "tt"})
        r = self.client.put(f"/api/drafts/{did}", headers=AUTH, json={"variants": {}})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["variants"], {})

    def test_variant_over_server_limit_rejected(self):
        huge = "x" * 281  # x text_max = 280
        r = self.client.post("/api/drafts", headers=AUTH,
                             json={"content": "main", "variants": {"x": huge}})
        self.assertEqual(r.status_code, 400)

    def test_unknown_network_key_is_ignored_not_fatal(self):
        r = self.client.post("/api/drafts", headers=AUTH,
                             json={"content": "main",
                                   "variants": {"unknownnet": "text", "x": "ok"}})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["variants"].get("x"), "ok")

    # ---------------- networks endpoint (source of truth) ----------------

    def test_networks_endpoint_lists_server_specs(self):
        r = self.client.get("/api/networks")
        self.assertEqual(r.status_code, 200)
        specs = r.json()
        for net in ("telegram", "x", "instagram", "youtube", "facebook", "tiktok"):
            self.assertIn(net, specs)
            self.assertIn("text_max", specs[net])

    # ---------------- standalone token auth (STUDIO_ADMIN_TOKEN) ----------------

    def test_bearer_token_accepted(self):
        r = self.client.get("/api/me",
                            headers=self.bearer)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["user"]["auth"], "token")
        self.assertEqual(body["user"]["id"], ADMIN_ID)

    def test_bearer_invalid_rejected(self):
        r = self.client.get("/api/me", headers={"Authorization": "Bearer wrong-token"})
        self.assertEqual(r.status_code, 401)
        self.assertIn("Invalid studio token", r.json()["detail"])

    def test_bearer_empty_value_rejected(self):
        r = self.client.get("/api/me", headers={"Authorization": "Bearer "})
        self.assertEqual(r.status_code, 401)
        self.assertIn("Invalid studio token", r.json()["detail"])

    def test_bearer_disabled_when_env_unset(self):
        saved = os.environ.get("STUDIO_ADMIN_TOKEN")
        try:
            os.environ.pop("STUDIO_ADMIN_TOKEN")
            r = self.client.get("/api/me",
                                headers=self.bearer)
            self.assertEqual(r.status_code, 401)  # falls through to tma rules
            self.assertIn("tma", r.json()["detail"])
        finally:
            os.environ["STUDIO_ADMIN_TOKEN"] = saved or ""

    def test_bearer_media_and_drafts_flow(self):
        h = self.bearer
        up = self.client.post("/api/media", headers=h,
                              files={"file": ("t2.png", PNG_1X1, "image/png")})
        self.assertEqual(up.status_code, 200, up.text)
        got = self.client.get(up.json()["url"], headers=h)
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.content, PNG_1X1)
        d = self.client.post("/api/drafts", headers=h, json={"content": "token draft"})
        self.assertEqual(d.status_code, 200)
        self.assertEqual(d.json()["content"], "token draft")

    def test_tma_still_works_alongside_bearer(self):
        r = self.client.get("/api/me", headers=AUTH)
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("auth", r.json()["user"])  # tma path returns the plain user

    # ---------------- db sanity under WORK_DIR isolation ----------------

    def test_db_is_isolated_to_workdir(self):
        # In the full suite another module may import voidfeed_db first, pinning
        # DB_PATH to its own temp WORK_DIR. What matters is isolation from the
        # PRODUCTION database, not a specific temp dir.
        prod_db = Path("/home/johnny/VoidFeedBot/data/voidfeed.sqlite3")
        self.assertNotEqual(Path(db.DB_PATH), prod_db)
        self.assertFalse(Path(db.DB_PATH).is_relative_to(prod_db.parent))
        self.assertTrue(db.DB_PATH.exists())
        self.assertNotIn("VoidFeedBot/data", str(db.DB_PATH))


if __name__ == "__main__":
    unittest.main()
