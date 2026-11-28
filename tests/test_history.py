"""Publishing history + scheduling lifecycle tests (studio API, isolated DB).

Covers:
- schedule action records an append-only 'scheduled' event
- unschedule records 'unscheduled'
- studio publish success records 'published', failure records 'failed'
- /api/history filtering + invalid event rejection
- history events never embed secrets; only safe fields
- migration idempotency (init_database runs twice)
"""
import os
import tempfile
import unittest
from unittest.mock import patch

from _fixtures import prepare_workspace
_TMP = prepare_workspace("hist")
os.environ["TELEGRAM_BOT_TOKEN"] = "12345:fake-bot-token-for-history"
os.environ["VOIDFEED_ADMIN_ID"] = "999000111"
os.environ["STUDIO_ADMIN_TOKEN"] = "hist-test-admin-token"
os.environ["VOIDFEED_DEMO"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

import studio  # noqa: E402
import voidfeed_db as db  # noqa: E402

H = {"Authorization": "Bearer hist-test-admin-token"}


class HistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_workspace("hist")

    def setUp(self):
        os.environ["STUDIO_ADMIN_TOKEN"] = "hist-test-admin-token"
        os.environ["VOIDFEED_ADMIN_ID"] = "999000111"
        os.environ["VOIDFEED_DEMO"] = "0"
        os.environ["TELEGRAM_BOT_TOKEN"] = "12345:fake-bot-token-for-history"
        self.client = TestClient(studio.app)
        self.h = {"Authorization": "Bearer hist-test-admin-token"}

    def _make_draft(self, channel_id=None):
        r = self.client.post("/api/drafts", headers=self.h,
                             json={"content": "test history draft", "channel_id": channel_id})
        self.assertEqual(r.status_code, 200)
        return r.json()["id"]

    def test_history_table_exists_and_migration_idempotent(self):
        db.init_database()
        db.init_database()  # second run must be safe
        # table exists and is queryable
        self.assertIsInstance(db.list_publish_events(), list)

    def test_schedule_records_event(self):
        ch = db.add_channel(-1005, "Hist Chan", "histchan")
        draft = self._make_draft(ch)
        r = self.client.post(f"/api/drafts/{draft}/schedule", headers=self.h,
                             json={"scheduled_at": "2026-12-01T12:00"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "scheduled")
        ev = [e for e in db.list_publish_events() if e["draft_id"] == draft]
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["event"], "scheduled")
        self.assertEqual(ev[0]["channel_id"], ch)
        self.assertIsNotNone(ev[0]["scheduled_at"])

    def test_unschedule_records_event(self):
        ch = db.add_channel(-1006, "Hist Chan2", "histchan2")
        draft = self._make_draft(ch)
        self.client.post(f"/api/drafts/{draft}/schedule", headers=self.h,
                         json={"scheduled_at": "2026-12-02T12:00"})
        r = self.client.post(f"/api/drafts/{draft}/unschedule", headers=self.h, json={})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "approved")
        events = [e["event"] for e in db.list_publish_events()]
        self.assertIn("scheduled", events)
        self.assertIn("unscheduled", events)

    def test_publish_success_records_event(self):
        ch = db.add_channel(-1007, "P Chan", "pchan")
        draft = self._make_draft(ch)
        with patch("httpx.post") as m:
            m.return_value.status_code = 200
            m.return_value.json.return_value = {"ok": True}
            r = self.client.post(f"/api/drafts/{draft}/publish", headers=self.h, json={})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "published")
        events = db.list_publish_events()
        self.assertTrue(any(e["event"] == "published" and e["draft_id"] == draft for e in events))

    def test_publish_failure_records_event(self):
        ch = db.add_channel(-1008, "F Chan", "fchan")
        draft = self._make_draft(ch)
        with patch("httpx.post") as m:
            m.return_value.status_code = 400
            m.return_value.json.return_value = {"ok": False, "description": "Photo_invalid_dimensions"}
            r = self.client.post(f"/api/drafts/{draft}/publish", headers=self.h, json={})
        self.assertEqual(r.status_code, 502)
        events = db.list_publish_events()
        self.assertTrue(any(e["event"] == "failed" and e["draft_id"] == draft for e in events))
        failed = next(e for e in events if e["event"] == "failed")
        self.assertIn("Photo_invalid_dimensions", failed["details"])

    def test_history_endpoint_lists_and_filters(self):
        ch = db.add_channel(-1009, "Api Chan", "apichan")
        draft = self._make_draft(ch)
        self.client.post(f"/api/drafts/{draft}/schedule", headers=self.h,
                         json={"scheduled_at": "2026-12-03T12:00"})
        all_ = self.client.get("/api/history", headers=self.h).json()
        self.assertGreaterEqual(len(all_), 1)
        # safe fields only
        for ev in all_:
            self.assertNotIn("token", ev)
            self.assertNotIn("secret", str(ev))
            self.assertNotIn("content", ev)  # snippet only
            self.assertIn("channel_title", ev)
        sched = self.client.get("/api/history?event=scheduled", headers=self.h).json()
        self.assertTrue(all(e["event"] == "scheduled" for e in sched))
        bad = self.client.get("/api/history?event=nope", headers=self.h)
        self.assertEqual(bad.status_code, 400)

    def test_history_requires_auth(self):
        r = self.client.get("/api/history")
        self.assertEqual(r.status_code, 401)


if __name__ == "__main__":
    unittest.main()
