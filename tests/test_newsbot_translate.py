"""newsbot translation-order tests — temp WORK_DIR, no live DB / network/token."""
import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

TMP = tempfile.mkdtemp(prefix="voidfeed_news_test_")
os.environ["WORK_DIR"] = TMP
os.environ["TELEGRAM_BOT_TOKEN"] = "123456:FAKE"
os.environ["VOIDFEED_ADMIN_ID"] = "220297612"

import newsbot  # noqa: E402


class TranslateOrderTests(unittest.TestCase):
    async def _translate(self, ai, mem, quick):
        with patch.object(newsbot, "_ai_translate",
                          new=AsyncMock(return_value=ai)), \
             patch.object(newsbot, "_mymemory_translate",
                          new=AsyncMock(return_value=mem)), \
             patch.object(newsbot, "_quick_fa", return_value=quick):
            return await newsbot._translate_fa("Some Big Movie Title Announced")

    def test_ai_first(self):
        out = asyncio.run(self._translate("برخی فیلم بزرگ اعلام شد", None, None))
        self.assertEqual(out, "برخی فیلم بزرگ اعلام شد")

    def test_falls_back_to_mymemory_when_ai_none(self):
        out = asyncio.run(self._translate(None, "ترجمه مای مموری", None))
        self.assertEqual(out, "ترجمه مای مموری")

    def test_last_resort_quick_dict(self):
        out = asyncio.run(self._translate(None, None, "ترجمه سریع"))
        self.assertEqual(out, "ترجمه سریع")

    def test_all_none_returns_none(self):
        out = asyncio.run(self._translate(None, None, None))
        self.assertIsNone(out)


class VideoRegexTests(unittest.TestCase):
    def test_og_video_inline_source(self):
        html = ('<video controls><source src="https://x.com/clip.mp4" '
                'type="video/mp4"></video>')
        self.assertEqual(newsbot._og_video_from(html),
                         "https://x.com/clip.mp4")

    def test_og_video_meta_still_works(self):
        html = ('<meta property="og:video" content="https://y.com/v.mp4">')
        self.assertEqual(newsbot._og_video_from(html),
                         "https://y.com/v.mp4")

    def test_og_video_none(self):
        self.assertEqual(newsbot._og_video_from("<p>no video</p>"), "")


class EmbedVideoTests(unittest.TestCase):
    def test_is_embed_video(self):
        self.assertTrue(newsbot._is_embed_video(
            "https://www.youtube.com/watch?v=abc"))
        self.assertTrue(newsbot._is_embed_video("https://youtu.be/abc"))
        self.assertTrue(newsbot._is_embed_video("https://vimeo.com/123"))
        self.assertFalse(newsbot._is_embed_video(
            "https://cdn.site.com/clip.mp4"))

    def test_append_embed(self):
        content = "#سینما\n\n📰 تیتر\n🔗 منبع: Variety\nhttps://x.com/a"
        out = newsbot._append_embed(
            content, "https://www.youtube.com/watch?v=abc")
        self.assertIn("🎬 تماشای ویدیو: https://www.youtube.com/watch?v=abc", out)
        # no dup, and non-embed url is ignored
        self.assertEqual(newsbot._append_embed(out, "https://www.youtube.com/watch?v=abc"), out)
        self.assertEqual(
            newsbot._append_embed(content, "https://cdn.site.com/clip.mp4"), content)


if __name__ == "__main__":
    unittest.main()
