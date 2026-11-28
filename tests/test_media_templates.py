"""Media library + Templates API tests (isolated DB)."""
import os
import tempfile
import unittest

from _fixtures import prepare_workspace
_TMP = prepare_workspace("media_tpl")
os.environ["TELEGRAM_BOT_TOKEN"] = "12345:fake-bot-token-for-media"
os.environ["VOIDFEED_ADMIN_ID"] = "999000111"
os.environ["STUDIO_ADMIN_TOKEN"] = "media-test-admin-token"
os.environ["VOIDFEED_DEMO"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

import studio  # noqa: E402
import voidfeed_db as db  # noqa: E402

H = {"Authorization": "Bearer media-test-admin-token"}
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c626001000000ffff03000006000557bfabd40000000049454e44ae426082")


class MediaTemplatesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_workspace("media")

    def setUp(self):
        os.environ["STUDIO_ADMIN_TOKEN"] = "media-test-admin-token"
        os.environ["VOIDFEED_ADMIN_ID"] = "999000111"
        os.environ["VOIDFEED_DEMO"] = "0"
        self.client = TestClient(studio.app)
        self.h = {"Authorization": "Bearer media-test-admin-token"}

    # media library

    def test_upload_adds_library_entry(self):
        up = self.client.post("/api/media", headers=self.h,
                              files={"file": ("t1.png", PNG, "image/png")})
        self.assertEqual(up.status_code, 200)
        url = up.json()["url"]
        lib = self.client.get("/api/media/library", headers=self.h).json()
        self.assertTrue(any(it["url"] == url for it in lib))
        self.assertNotIn("content", lib[0])

    def test_library_requires_auth(self):
        self.assertEqual(self.client.get("/api/media/library").status_code, 401)

    def test_library_update_alt_caption(self):
        up = self.client.post("/api/media", headers=self.h,
                              files={"file": ("t2.png", PNG, "image/png")}).json()
        item = self.client.get("/api/media/library", headers=self.h).json()[0]
        r = self.client.put(f"/api/media/library/{item['id']}", headers=self.h,
                            json={"alt_text": "alt x", "caption": "cap y"})
        self.assertEqual(r.status_code, 200)
        item2 = self.client.get("/api/media/library", headers=self.h).json()[0]
        self.assertEqual(item2["alt_text"], "alt x")
        self.assertEqual(item2["caption"], "cap y")

    def test_delete_unreferenced(self):
        up = self.client.post("/api/media", headers=self.h,
                              files={"file": ("t3.png", PNG, "image/png")}).json()
        fname = up["url"].rsplit("/", 1)[1]
        item = next(it for it in self.client.get("/api/media/library", headers=self.h).json()
                    if it["filename"] == fname)
        r = self.client.delete(f"/api/media/library/{item['id']}", headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertFalse((db.MEDIA_DIR / fname).exists())
        lib = self.client.get("/api/media/library", headers=self.h).json()
        self.assertFalse(any(it["id"] == item["id"] for it in lib))

    def test_delete_referenced_blocked(self):
        up = self.client.post("/api/media", headers=self.h,
                              files={"file": ("t4.png", PNG, "image/png")}).json()
        item = self.client.get("/api/media/library", headers=self.h).json()[0]
        # create a draft referencing this media
        draft = self.client.post("/api/drafts", headers=self.h,
                                 json={"content": "uses media", "media_url": up["url"]}).json()
        self.assertEqual(draft["status"], "draft")
        r = self.client.delete(f"/api/media/library/{item['id']}", headers=self.h)
        self.assertEqual(r.status_code, 409)
        # file still exists
        self.assertTrue((db.MEDIA_DIR / item["filename"]).exists())

    # templates

    def test_templates_crud(self):
        r = self.client.post("/api/templates", headers=self.h,
                             json={"name": "t1", "body": "hello {title}"})
        self.assertEqual(r.status_code, 200)
        tid = r.json()["id"]
        rows = self.client.get("/api/templates", headers=self.h).json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "t1")
        r2 = self.client.put(f"/api/templates/{tid}", headers=self.h,
                             json={"name": "t1b", "body": "updated"})
        self.assertEqual(r2.status_code, 200)
        rows = self.client.get("/api/templates", headers=self.h).json()
        self.assertEqual(rows[0]["body"], "updated")
        r3 = self.client.delete(f"/api/templates/{tid}", headers=self.h)
        self.assertEqual(r3.status_code, 200)
        self.assertEqual(self.client.get("/api/templates", headers=self.h).json(), [])

    def test_templates_validation(self):
        r = self.client.post("/api/templates", headers=self.h,
                             json={"name": "", "body": "x"})
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/templates", headers=self.h,
                             json={"name": "x", "body": ""})
        self.assertEqual(r.status_code, 400)

    def test_templates_require_auth(self):
        self.assertEqual(self.client.get("/api/templates").status_code, 401)
        self.assertEqual(self.client.post("/api/templates", json={"name": "a", "body": "b"}).status_code, 401)


if __name__ == "__main__":
    unittest.main()
