import os
import sys
import tempfile

import unittest

from _fixtures import prepare_workspace
TMP = prepare_workspace("brand")
os.environ["TELEGRAM_BOT_TOKEN"] = "12345:fake-token"
os.environ["VOIDFEED_ADMIN_ID"] = "999000111"
os.environ["STUDIO_ADMIN_TOKEN"] = "stage-token"
os.environ["VOIDFEED_DEMO"] = "0"
for k in ("AI_API_BASE", "AI_API_KEY", "AI_MODEL", "AI_FALLBACK_MODELS"):
    os.environ[k] = ""

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
import studio
import voidfeed_db as db

H = {"Authorization": "Bearer stage-token"}


class BrandProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_workspace("brand")

    def setUp(self):
        os.environ["STUDIO_ADMIN_TOKEN"] = "stage-token"
        os.environ["VOIDFEED_ADMIN_ID"] = "999000111"
        os.environ["VOIDFEED_DEMO"] = "0"
        os.environ["TELEGRAM_BOT_TOKEN"] = "12345:fake-token"
        self.client = TestClient(studio.app)
        self.h = {"Authorization": "Bearer stage-token"}

    def test_profile_defaults(self):
        r = self.client.get("/api/profile", headers=self.h)
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d["brand"]["email"], "voidfeedteam@gmail.com")
        self.assertIn("خوراکِ", d["brand"]["name_fa"])
        self.assertEqual(len(d["social"]), 10)
        byid = {p["id"]: p for p in d["social"]}
        # all ten official platforms carry their exact public URL
        EXPECTED = {
            "telegram": "https://t.me/FeedTheVoids",
            "instagram": "https://instagram.com/voidfeedmedia",
            "facebook": "https://facebook.com/TheVoidFeedMedia",
            "youtube": "https://youtube.com/@voidfeedmedia",
            "x": "https://x.com/VoidFeedMedia",
            "tiktok": "https://www.tiktok.com/@voidfeedmedia",
            "quora": "https://www.quora.com/profile/Void-Feed-Media",
            "github": "https://github.com/voidfeedmedia",
            "discord": "https://discord.com/users/1563034001378382005",
        }
        for pid, url in EXPECTED.items():
            self.assertEqual(byid[pid]["url"], url)
        self.assertTrue(byid["clubhouse"]["url"].startswith("https://www.clubhouse.com/@voidfeedmedia"))
        # WhatsApp / Email are contact methods — they are NOT social cards
        self.assertNotIn("whatsapp", byid)
        self.assertNotIn("email", byid)
        # TikTok handle corrected
        self.assertEqual(byid["tiktok"]["handle"], "@voidfeedmedia")
        # Discord is a personal user profile, not a server invite
        self.assertEqual(byid["discord"]["profile_type"], "user_profile")
        # Honest statuses: fake token => Telegram cannot be verified; others are
        # user-supplied and unverified (never a green checkmark for presence alone)
        self.assertEqual(byid["telegram"]["status"], "unverified")
        self.assertFalse(byid["telegram"]["verified"])
        for pid, p in byid.items():
            self.assertIn(p["status"], ("verified", "unverified"))
            self.assertEqual(p["verified"], p["status"] == "verified")
        self.assertEqual(byid["discord"]["logo"], "/static-assets/icons/platforms/discord.svg")
        self.assertIsNone(byid["discord"]["logo_pending"])
        self.assertEqual(byid["clubhouse"]["logo"], "/static-assets/icons/platforms/clubhouse.svg")

    def test_telegram_verified_only_on_real_chat_check(self):
        # patch the real getChat check: positive result => verified
        orig = studio._tg_verify_handle
        studio._tg_verify_handle = lambda handle: True
        try:
            r = self.client.get("/api/profile", headers=self.h)
            byid = {p["id"]: p for p in r.json()["social"]}
            self.assertEqual(byid["telegram"]["status"], "verified")
            self.assertTrue(byid["telegram"]["verified"])
            # non-Telegram never flips to verified via the patch
            self.assertEqual(byid["x"]["status"], "unverified")
        finally:
            studio._tg_verify_handle = orig

    def test_profile_edit_and_invalid(self):
        r = self.client.put("/api/profile", headers=self.h, json={
            "brand_desc_fa": "معرفی تستی",
            "brand_desc_en": "test intro",
            "social": {"telegram": {"url": "https://t.me/feedthevoids", "handle": "@FeedTheVoids"}},
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["desc_fa"], "معرفی تستی")
        bad = self.client.put("/api/profile", headers=self.h, json={
            "social": {"x": {"url": "not-a-url"}},
        })
        self.assertEqual(bad.status_code, 400)

    def test_profile_auth_required(self):
        self.assertEqual(self.client.get("/api/profile").status_code, 401)

    def test_connections_spec(self):
        r = self.client.get("/api/connections/spec", headers=self.h)
        self.assertEqual(r.status_code, 200)
        rows = r.json()
        self.assertEqual(len(rows), 10)
        blob = str(rows)
        # no fake connected states
        for row in rows:
            self.assertNotEqual(row["technical"]["status"], "connected")
        self.assertNotIn("sk-", blob)
        self.assertNotIn("dahl_", blob)
        self.assertNotIn("Bearer", blob)
        tg = next(x for x in rows if x["id"] == "telegram")
        self.assertEqual(tg["technical"]["kind"], "bot_api")
        self.assertIn("publish_via_bot", tg["technical"]["capabilities"])
        ig = next(x for x in rows if x["id"] == "instagram")
        self.assertEqual(ig["technical"]["status"], "not_implemented")
        self.assertEqual(ig["technical"]["guidance"], "instagram")

    def test_connections_auth_required(self):
        self.assertEqual(self.client.get("/api/connections/spec").status_code, 401)

    def test_github_shared_across_profile_and_connections(self):
        prof = self.client.get("/api/profile", headers=self.h).json()
        ps = {p["id"]: p for p in prof["social"]}
        rows = self.client.get("/api/connections/spec", headers=self.h).json()
        cs = {p["id"]: p for p in rows}
        self.assertIn("github", ps)
        self.assertIn("github", cs)
        # same canonical URL + display in both sections, from the same registry
        self.assertEqual(ps["github"]["url"], "https://github.com/voidfeedmedia")
        self.assertEqual(cs["github"]["social_profile"]["url"], ps["github"]["url"])
        self.assertEqual(cs["github"]["social_profile"]["display"], ps["github"]["display"])


if __name__ == "__main__":
    unittest.main()
