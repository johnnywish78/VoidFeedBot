"""Phase 2 P1 tests: Telegram media validation, Bot retry loop, news publish.

Covers the mission brief items:
- sendPhoto / sendVideo constraints (size, format, dimensions, aspect)
- Bot publish_draft retry loop + duplicate-publishing prevention
- News image/video pre-flight validation and Telegram failure recording
"""
import asyncio
import os
import tempfile
import unittest
from pathlib import Path

from _fixtures import clear_data, prepare_workspace, reset_workspace
prepare_workspace("publish")

os.environ["TELEGRAM_BOT_TOKEN"] = "12345:fake-publish-token"
os.environ["VOIDFEED_ADMIN_ID"] = "999000111"
os.environ["STUDIO_ADMIN_TOKEN"] = "publish-test-token"
os.environ["VOIDFEED_DEMO"] = "0"

from PIL import Image  # noqa: E402

import media_validate as mv  # noqa: E402
import voidfeed_db as db  # noqa: E402
import bot as botmod  # noqa: E402
import newsbot  # noqa: E402


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, **kw):
        self.sent.append(("message", kw))
        return {"ok": True}

    async def send_photo(self, **kw):
        self.sent.append(("photo", kw))
        return {"ok": True}

    async def send_video(self, **kw):
        self.sent.append(("video", kw))
        return {"ok": True}


def _write_png(d: Path, w: int, h: int) -> Path:
    p = d / f"{w}x{h}.png"
    Image.new("RGB", (w, h)).save(p)
    return p


class MediaValidationTests(unittest.TestCase):
    """Telegram Bot API sendPhoto/sendVideo constraints (from docs)."""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="vfb_mv_"))

    # ---- sendPhoto ----
    def test_photo_accepts_small_valid_png(self):
        p = _write_png(self.d, 100, 80)
        self.assertIsNone(mv.validate_photo(str(p)))

    def test_photo_rejects_missing_file(self):
        self.assertEqual(mv.validate_photo(str(self.d / "nope.png")),
                         "پرونده رسانه پیدا نشد")

    def test_photo_rejects_oversized(self):
        p = _write_png(self.d, 10, 10)
        with open(p, "r+b") as fh:
            fh.truncate(10 * 1024 * 1024 + 1)
        self.assertEqual(mv.validate_photo(str(p)),
                         "عکس حداکثر ۱۰ مگابایت است (Telegram Bot API)")

    def test_photo_rejects_dim_sum_over_10000(self):
        # width+height > 10000 is not sendable
        p = _write_png(self.d, 9900, 200)  # 10100
        self.assertTrue("ابعاد" in mv.validate_photo(str(p)))

    def test_photo_rejects_aspect_over_20(self):
        p = _write_png(self.d, 3000, 50)  # ratio 60
        self.assertTrue("نسبت" in mv.validate_photo(str(p)))

    def test_photo_rejects_non_image_bytes(self):
        p = self.d / "fake.png"
        p.write_bytes(b"not an image at all")
        self.assertEqual(mv.validate_photo(str(p)),
                         "فایل تصویر نامعتبر است")

    # ---- sendVideo ----
    def test_video_accepts_minimal_mp4_with_ftyp(self):
        p = self.d / "ok.mp4"
        p.write_bytes(b"\x00\x00\x00\x18ftypisom........")
        self.assertIsNone(mv.validate_video(str(p)))

    def test_video_rejects_non_mp4_extension(self):
        p = self.d / "clip.mov"
        p.write_bytes(b"\x00\x00\x00\x18ftypisom........")
        self.assertEqual(mv.validate_video(str(p)), "ویدیو باید MP4 باشد")

    def test_video_rejects_missing_ftyp(self):
        p = self.d / "bad.mp4"
        p.write_bytes(b"this is not an mp4 file at all")
        self.assertEqual(mv.validate_video(str(p)),
                         "فایل ویدیوی نامعتبر است")

    def test_video_rejects_oversized(self):
        p = self.d / "big.mp4"
        p.write_bytes(b"\x00\x00\x00\x18ftypisom........")
        with open(p, "r+b") as fh:
            fh.truncate(50 * 1024 * 1024 + 1)
        self.assertEqual(mv.validate_video(str(p)),
                         "ویدیو حداکثر ۵۰ مگابایت است (Telegram Bot API)")


class BotPublishRetryTests(unittest.TestCase):
    """Bot publish_draft: retry loop, duplicate guard, outcome recording."""

    @classmethod
    def setUpClass(cls):
        prepare_workspace("publish_bot")

    def setUp(self):
        prepare_workspace("publish_bot")
        clear_data()
        self.ch = db.add_channel(-100123, "Test Channel", "testchan")
        self.bot = FakeBot()

    def _draft(self, **kw):
        base = dict(channel_id=self.ch, content="hello",
                    media_kind=None, media_path=None,
                    status="scheduled", attempts=0)
        base.update(kw)
        did = db.save_draft(
            base["content"], channel_id=base["channel_id"],
            media_path=base["media_path"], media_kind=base["media_kind"],
            source="test")
        db.update_draft(did, attempts=base["attempts"])
        if base["status"] != "draft":
            db.set_draft_status(did, base["status"])
        return dict(db.get_draft(did))

    def _events(self, draft_id):
        return [dict(e) for e in db.list_publish_events()
                if e["draft_id"] == draft_id]

    def test_skips_already_published(self):
        row = self._draft(status="published")
        asyncio.run(botmod.publish_draft(self.bot, row))
        self.assertEqual(self.bot.sent, [])
        self.assertEqual(self._events(row["id"]), [])

    def test_success_records_published_and_clears_attempts(self):
        row = self._draft(attempts=2, publish_error="old error")
        asyncio.run(botmod.publish_draft(self.bot, row))
        self.assertEqual([k for k, _ in self.bot.sent], ["message"])
        d = dict(db.get_draft(row["id"]))
        self.assertEqual(d["status"], "published")
        self.assertEqual(d["attempts"], 0)
        self.assertIsNone(d["publish_error"])
        ev = self._events(row["id"])
        self.assertEqual([e["event"] for e in ev], ["published"])
        self.assertEqual(ev[0]["triggered_by"], "bot")

    def test_failure_increments_attempts_and_fails_after_3(self):
        class BoomBot(FakeBot):
            async def send_message(self, **kw):
                raise RuntimeError("telegram down")

        b = BoomBot()
        base = self._draft()
        did = base["id"]
        for i in range(1, 4):
            with self.subTest(attempt=i):
                asyncio.run(botmod.publish_draft(b, dict(db.get_draft(did))))
                d = dict(db.get_draft(did))
                self.assertEqual(d["attempts"], i)
                self.assertIn("telegram down", d["publish_error"])
                if i < 3:
                    self.assertEqual(d["status"], "scheduled")
                else:
                    self.assertEqual(d["status"], "publish_failed")
        ev = self._events(did)
        self.assertEqual([e["event"] for e in ev], ["failed"] * 3)
        self.assertTrue(all(e["triggered_by"] == "bot" for e in ev))

    def test_invalid_media_never_calls_telegram(self):
        row = self._draft(media_kind="photo", media_path="/nope/photo.png")
        asyncio.run(botmod.publish_draft(self.bot, row))
        self.assertEqual(self.bot.sent, [])
        d = dict(db.get_draft(row["id"]))
        self.assertEqual(d["attempts"], 1)
        self.assertEqual(d["publish_error"], "پرونده رسانه پیدا نشد")


class NewsPublishValidationTests(unittest.TestCase):
    """News path: pre-flight validation + Telegram failure recording."""

    @classmethod
    def setUpClass(cls):
        prepare_workspace("publish_news")

    def setUp(self):
        prepare_workspace("publish_news")
        clear_data()
        self.ch = db.add_channel(-100456, "News Channel", "newsch")
        self.bot = FakeBot()

    def test_invalid_video_rejected_before_telegram(self):
        bad = Path("/tmp/definitely_missing_news_video.mp4")
        ok, err = asyncio.run(newsbot._publish(
            self.bot, {"chat_id": -100456}, "text", None, str(bad)))
        self.assertFalse(ok)
        self.assertEqual(err, "پرونده رسانه پیدا نشد")
        self.assertEqual(self.bot.sent, [])

    def test_text_message_publish_succeeds(self):
        ok, err = asyncio.run(newsbot._publish(
            self.bot, {"chat_id": -100456}, "some news text", None, None))
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertEqual([k for k, _ in self.bot.sent], ["message"])

    def test_photo_publish_succeeds(self):
        with tempfile.TemporaryDirectory() as d:
            img = _write_png(Path(d), 200, 100)
            ok, err = asyncio.run(newsbot._publish(
                self.bot, {"chat_id": -100456}, "cap", str(img), None))
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertEqual([k for k, _ in self.bot.sent], ["photo"])

    def test_failure_records_attempts_and_fails_after_3(self):
        class BoomBot(FakeBot):
            async def send_message(self, **kw):
                raise RuntimeError("api 429")

        b = BoomBot()
        draft_id = db.save_draft("news", channel_id=self.ch,
                                 source="news", status="approved")
        for i in range(1, 4):
            with self.subTest(attempt=i):
                row = db.get_draft(draft_id)
                ok, err = asyncio.run(newsbot._publish(
                    b, {"chat_id": -100456}, row["content"], None, None))
                self.assertFalse(ok)
                newsbot._record_publish_result(row, ok, self.ch, err)
                d = dict(db.get_draft(draft_id))
                self.assertEqual(d["attempts"], i)
                if i < 3:
                    self.assertEqual(d["status"], "approved")
                else:
                    self.assertEqual(d["status"], "publish_failed")
        ev = [dict(e) for e in db.list_publish_events()
              if e["draft_id"] == draft_id]
        self.assertEqual([e["event"] for e in ev], ["failed"] * 3)
        self.assertTrue(all(e["triggered_by"] == "news" for e in ev))


if __name__ == "__main__":
    unittest.main()
