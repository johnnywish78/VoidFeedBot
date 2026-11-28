"""contentgen tests — temp WORK_DIR, no live DB, no real network/token."""
import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

TMP = tempfile.mkdtemp(prefix="voidfeed_gen_test_")
os.environ["WORK_DIR"] = TMP
os.environ["TELEGRAM_BOT_TOKEN"] = "123456:FAKE_TOKEN_FOR_TEST"
os.environ["VOIDFEED_ADMIN_ID"] = "220297612"

import voidfeed_db as db  # noqa: E402  (pins DB path from WORK_DIR)
import contentgen          # noqa: E402
import studio              # noqa: E402  (for patching ai_chat)


def _reset_settings():
    for k in ("gen_enabled", "gen_interval_min", "gen_sections",
              "gen_cursor", "gen_last_title", "gen_last_at",
              "gen_last_error"):
        db.set_setting(k, "")


def _clear_channels():
    for c in db.list_channels():
        db.remove_channel(c["id"])


def _dummy_img(text, topic):
    p = db.MEDIA_DIR / "test_cover.jpg"
    db.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\xff\xd8\xff" + b"0" * 128)
    return str(p)


class ContentGenTests(unittest.TestCase):
    def setUp(self):
        db.init_database()
        _reset_settings()
        db.set_setting("gen_enabled", "1")
        db.set_setting("gen_interval_min", "60")

    def test_all_topics_flatten(self):
        topics = contentgen._all_topics()
        self.assertEqual(len(topics), 14)  # cinema 2 + series 2 + music 4 + games 6
        cats = {t["cat"] for t in topics}
        self.assertEqual(cats, {"cinema", "series", "music", "games"})
        start = contentgen._cursor()
        contentgen._set_cursor(start + 1)
        self.assertEqual(contentgen._cursor(), (start + 1) % 14)

    def test_section_filter_topics(self):
        db.set_setting("gen_sections", "cinema,games")
        topics = contentgen._all_topics()
        self.assertEqual({t["cat"] for t in topics}, {"cinema", "games"})
        self.assertEqual(len(topics), 8)

    def test_build_prompt(self):
        topic = contentgen._all_topics()[0]
        prompt = contentgen._build_prompt(topic)
        self.assertIn(topic["fa"], prompt)
        self.assertIn("#" + topic["tag"], prompt)
        self.assertIn("به زبان اصلی", prompt)
        self.assertIn("۹۵۰", prompt)

    def test_clean_text_and_fit(self):
        raw = "🎬 **Título**\n\n\nخط بعدی…\n"
        self.assertEqual(contentgen._clean_text(raw), "🎬 Título\n\nخط بعدی…")
        long = "جمله اول اینجا هست. " + "کلمات " * 250
        fit = contentgen._fit_caption(long, limit=1000)
        self.assertLessEqual(len(fit), 1001)
        self.assertTrue(fit.endswith(("…", ".")) or fit.rstrip().endswith("."))

    def test_normalize_post_breaks_numbered_items(self):
        messy = ("🎬 فیلمها: 1. Inception — شرحی. 2️⃣ Tenet — شرحی."
                 " 3 Interstellar — شرحی.\n#سینما")
        out = contentgen._normalize_post(messy)
        lines = [l for l in out.splitlines() if l.strip()]
        self.assertGreaterEqual(len(lines), 4)
        self.assertTrue(any(l.startswith("1.") or l.startswith("1️⃣") for l in lines))
        self.assertNotIn("**", out)

    def test_run_once_no_channel(self):
        _clear_channels()
        result = asyncio.run(contentgen.run_once(bot=None))
        self.assertIn("error", result)

    def test_run_once_publishes_as_admin(self):
        _clear_channels()
        db.add_channel(-100111222333, "Test Channel")
        with patch.object(contentgen, "_cover_image", side_effect=_dummy_img), \
             patch.object(contentgen, "_publish",
                          new=AsyncMock(return_value=(True, None))), \
             patch.object(studio, "ai_chat",
                          new=AsyncMock(return_value=(
                              "🎬 بهترین فیلم‌های سینمایی\n"
                              "این هفته چند فیلم درخشان اکران شد…\n"
                              "\n#سینما #فیلم"))):
            result = asyncio.run(contentgen.run_once(bot=None))
        self.assertTrue(result.get("published"))
        draft = db.get_draft(result["draft_id"])
        self.assertIsNotNone(draft)
        self.assertEqual(draft["status"], "published")
        self.assertEqual(draft["source"], "contentgen")
        self.assertTrue(draft["media_path"])
        self.assertTrue(db.get_setting("gen_last_title", ""))


    def test_run_once_no_publish_when_cfg_ai_fails(self):
        _clear_channels()
        db.add_channel(-100111222333, "Test Channel")
        from fastapi import HTTPException
        def _boom(messages):
            raise HTTPException(502, "available tokens exhausted")
        with patch.object(contentgen, "_cover_image", side_effect=_dummy_img), \
             patch.object(contentgen, "_publish",
                          new=AsyncMock(return_value=(True, None))), \
             patch.object(studio, "ai_chat", side_effect=_boom):
            result = asyncio.run(contentgen.run_once(bot=None))
        self.assertIn("error", result)
        self.assertFalse(result.get("published"))
        self.assertTrue(db.get_setting("gen_last_error", ""))


if __name__ == "__main__":
    unittest.main()
