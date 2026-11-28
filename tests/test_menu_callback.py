"""Menu callback tests — fake Update/Context, temp WORK_DIR, no network."""
import os
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, patch

TMP = tempfile.mkdtemp(prefix="voidfeed_menu_test_")
os.environ["WORK_DIR"] = TMP
os.environ["TELEGRAM_BOT_TOKEN"] = "123456:FAKE"
ADMIN_ID = 220297612
os.environ["VOIDFEED_ADMIN_ID"] = str(ADMIN_ID)

import bot  # noqa: E402
import contentgen  # noqa: E402


class FakeUser:
    def __init__(self, uid):
        self.id = uid


class FakeMsg:
    chat_id = 12345


class FakeQuery:
    def __init__(self, data, uid=ADMIN_ID):
        self.data = data
        self.from_user = FakeUser(uid)
        self.message = FakeMsg()
        self.edited = None
        self.answered = False
        self.alert_shown = False

    async def answer(self, text=None, show_alert=False, **kw):
        self.answered = True
        if show_alert:
            self.alert_shown = True

    async def edit_message_text(self, text, reply_markup=None):
        self.edited = text


class FakeUpdate:
    def __init__(self, query):
        self.callback_query = query


def _ctx():
    return types.SimpleNamespace(
        application=types.SimpleNamespace(
            bot_data={"admin_id": ADMIN_ID}),
        bot=object())


class MenuCallbackTests(unittest.TestCase):
    def setUp(self):
        import voidfeed_db as db
        db.init_database()

    async def _run(self, data, uid=ADMIN_ID):
        q = FakeQuery(data, uid)
        await bot.menu_callback(FakeUpdate(q), _ctx())
        return q

    def test_main_menu_nav(self):
        q = asyncio_run(self._run("menu:news"))
        self.assertIn("اخبار", q.edited)

    def test_back_to_main(self):
        q = asyncio_run(self._run("menu:main"))
        self.assertIn("سلام", q.edited)

    def test_news_status_action(self):
        q = asyncio_run(self._run("act:news:status"))
        self.assertIn("وضعیت اخبار", q.edited)

    def test_english_callback_when_lang_en(self):
        import voidfeed_db as db
        db.set_setting("lang", "en")
        try:
            q = asyncio_run(self._run("menu:news"))
            self.assertIn("Auto news", q.edited)
            q2 = asyncio_run(self._run("act:news:status"))
            self.assertIn("Auto-news status", q2.edited)
        finally:
            db.set_setting("lang", "fa")

    def test_gen_status_action(self):
        q = asyncio_run(self._run("act:gen:status"))
        self.assertIn("وضعیت تولید پست", q.edited)

    def test_drafts_queue_empty(self):
        q = asyncio_run(self._run("act:drafts:queue"))
        self.assertIn("پیش‌نویس", q.edited)

    def test_gen_now_callback_publishes(self):
        with patch.object(contentgen, "run_once",
                          new=AsyncMock(return_value={
                              "published": True, "title": "🎬 تست"})):
            q = asyncio_run(self._run("act:gen:now:cinema"))
        self.assertIn("✅ پست تولید و منتشر شد", q.edited)

    def test_non_admin_rejected(self):
        q = asyncio_run(self._run("act:news:status", uid=999))
        self.assertTrue(q.answered)
        self.assertTrue(q.alert_shown)
        self.assertIsNone(q.edited)

    def test_lang_command_sets_setting(self):
        import voidfeed_db as db
        class M:
            chat_id = 12345
            async def reply_text(self, text):
                self.text = text
        m = M()
        upd = types.SimpleNamespace(
            effective_message=m,
            effective_user=FakeUser(ADMIN_ID),
            effective_chat=types.SimpleNamespace(type="private"))
        ctx = types.SimpleNamespace(
            args=["en"],
            application=types.SimpleNamespace(bot_data={"admin_id": ADMIN_ID}),
            bot=object())
        asyncio_run(bot.lang_command(upd, ctx))
        self.assertEqual(db.get_setting("lang"), "en")
        self.assertIn("Language", m.text)
        db.set_setting("lang", "fa")


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)


if __name__ == "__main__":
    unittest.main()
