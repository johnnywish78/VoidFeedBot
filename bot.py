"""VoidFeedBot — Telegram bot core + studio + auto-publisher."""
import asyncio
import logging
import os
import re
import secrets
import time as _time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
import httpx
from telegram import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonCommands,
    MenuButtonWebApp,
    Update,
    WebAppInfo,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import voidfeed_db as db
import moderator as mod
from media_validate import validate_media

BASE_DIR = Path(os.environ.get("WORK_DIR", Path(__file__).resolve().parent))
STUDIO_URL = os.environ.get("STUDIO_URL", "http://127.0.0.1:8077").strip()
MAX_DRAFT_LENGTH = 10000
QUEUE_LIMIT = 10
PUBLISH_TICK = 20
MAX_PUBLISH_ATTEMPTS = 3

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("VoidFeedBot")

# ---------------- i18n (fa/en) ----------------
LANG_DEFAULT = "fa"

T = {
    "fa": {
        "deny": "این بات خصوصی است و دسترسی شما مجاز نیست.",
        "hello": ("سلام! 🌌\n\nبه VoidFeed خوش آمدی — دسترسی مدیر تأیید شد.\n"
                  "از منوی زیر یک بخش را انتخاب کن؛ فهرست کامل فرمان‌ها در /help است."),
        "mn_news": "📰 اخبار", "mn_gen": "🎬 تولید پست",
        "mn_drafts": "📝 پیش‌نویس‌ها", "mn_studio": "🌌 استودیو",
        "mn_help": "❓ راهنما",
        "back": "◀️ بازگشت", "back_main": "◀️ بازگشت به منوی اصلی",
        "status_label": "وضعیت",
        "sched_label": "ساعات انتشار",
        "mn_cinema": "سینما", "mn_series": "سریال",
        "mn_music": "موسیقی", "mn_games": "بازی",
        "gen_next": "پست بعدی (چرخشی)",
        "drafts_q": "فهرست پیش‌نویس‌ها",
        "drafts_help_label": "مدیریت پیش‌نویس",
        "news_title": "📰 اخبار خودکار:", "gen_title": "🎬 تولید پست با AI:",
        "drafts_title": "📝 پیش‌نویس‌ها:",
        "on_news": "✅ انتشار خودکار اخبار روشن شد.",
        "off_news": "⛔️ انتشار خودکار اخبار خاموش شد.",
        "on_gen": "✅ تولید خودکار پست روشن شد.",
        "off_gen": "⛔️ تولید خودکار پست خاموش شد.",
        "st_news": "📰 وضعیت اخبار خودکار: {s}",
        "st_gen": "🎬 وضعیت تولید پست: {s}",
        "on_str": "روشن", "off_str": "خاموش",
        "interval": "بازه: هر {n} دقیقه",
        "sections": "بخش‌ها: {l}",
        "topics": "موضوعات: {t}", "topics_all": "همه",
        "auto_pub": "انتشار خودکار: {v}", "yes": "بله", "no": "خیر",
        "processed": "اخبار پردازش‌شده: {n}",
        "last_err": "آخرین خطا: {e}", "last_post": "آخرین پست: {t}",
        "sched_info": ("⏰ زمان‌بندی دستی نیاز به ورودی دارد:\n"
                       "/news sched 09:00 12:30 21:00 — ساعات انتشار (تهران)\n"
                       "/news sched off — بازگشت به حالت بازه‌ای"),
        "working_news": "🔄 در حال دریافت خبر…",
        "working_gen": "🔄 در حال تولید پست… (تا یک دقیقه)",
        "published_news": "✅ منتشر شد: {t}",
        "published_gen": "✅ پست تولید و منتشر شد.",
        "draft_news": "📝 پیش‌نویس #{id} ساخته شد (انتشار خودکار خاموش است).",
        "draft_gen": "📝 پیش‌نویس #{id} ساخته شد (انتشار ناموفق).",
        "err_fmt": "❌ {e}",
        "queue_empty": "هنوز پیش‌نویسی ثبت نشده است. با /draft شروع کن.",
        "queue_title": "فهرست پیش‌نویس‌ها (حداکثر ۱۰ مورد):",
        "drafts_manage": ("مدیریت پیش‌نویس با شناسه:\n"
                          "/approve ID — تأیید\n/reject ID — رد\n"
                          "/publish ID — انتشار فوری\n/cancel ID — لغو زمان‌بندی\n"
                          "/delete ID — حذف"),
        "lang_done": "✅ زبان تغییر کرد: {l}",
        "lang_usage": "استفاده: /lang en یا /lang fa",
    },
    "en": {
        "deny": "This bot is private; you are not authorized.",
        "hello": ("Hello! 🌌\n\nWelcome to VoidFeed — admin access confirmed.\n"
                  "Pick a section from the menu below; full command list in /help."),
        "mn_news": "📰 News", "mn_gen": "🎬 Generate post",
        "mn_drafts": "📝 Drafts", "mn_studio": "🌌 Studio",
        "mn_help": "❓ Help",
        "back": "◀️ Back", "back_main": "◀️ Back to main menu",
        "status_label": "Status",
        "sched_label": "Schedule hours",
        "mn_cinema": "Cinema", "mn_series": "Series",
        "mn_music": "Music", "mn_games": "Games",
        "gen_next": "Next post (rotate)",
        "drafts_q": "Draft list",
        "drafts_help_label": "Manage drafts",
        "news_title": "📰 Auto news:", "gen_title": "🎬 AI post generation:",
        "drafts_title": "📝 Drafts:",
        "on_news": "✅ Auto news publishing ON.",
        "off_news": "⛔️ Auto news publishing OFF.",
        "on_gen": "✅ Auto post generation ON.",
        "off_gen": "⛔️ Auto post generation OFF.",
        "st_news": "📰 Auto-news status: {s}",
        "st_gen": "🎬 Post-generation status: {s}",
        "on_str": "ON", "off_str": "OFF",
        "interval": "Interval: every {n} minutes",
        "sections": "Sections: {l}",
        "topics": "Topics: {t}", "topics_all": "all",
        "auto_pub": "Auto-publish: {v}", "yes": "yes", "no": "no",
        "processed": "News processed: {n}",
        "last_err": "Last error: {e}", "last_post": "Last post: {t}",
        "sched_info": ("⏰ Manual schedule needs input:\n"
                       "/news sched 09:00 12:30 21:00 — publish hours (Tehran)\n"
                       "/news sched off — back to interval mode"),
        "working_news": "🔄 Fetching news…",
        "working_gen": "🔄 Generating post… (up to a minute)",
        "published_news": "✅ Published: {t}",
        "published_gen": "✅ Post generated and published.",
        "draft_news": "📝 Draft #{id} created (auto-publish is off).",
        "draft_gen": "📝 Draft #{id} created (publishing failed).",
        "err_fmt": "❌ {e}",
        "queue_empty": "No drafts yet. Start with /draft.",
        "queue_title": "Draft list (up to 10):",
        "drafts_manage": ("Manage drafts by ID:\n"
                          "/approve ID — approve\n/reject ID — reject\n"
                          "/publish ID — publish now\n/cancel ID — cancel schedule\n"
                          "/delete ID — delete"),
        "lang_done": "✅ Language set: {l}",
        "lang_usage": "Usage: /lang en or /lang fa",
    },
}


def _lang() -> str:
    v = db.get_setting("lang", LANG_DEFAULT)
    return v if v in T else LANG_DEFAULT


def tr(key: str) -> str:
    d = T.get(_lang()) or T[LANG_DEFAULT]
    return d.get(key, T[LANG_DEFAULT].get(key, key))


def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    chat = update.effective_chat
    admin_id = context.application.bot_data.get("admin_id")
    return (
        user is not None
        and chat is not None
        and chat.type == "private"
        and user.id == admin_id
    )


async def deny_access(update: Update) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(tr("deny"))


def clear_pending(context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.user_data is not None:
        context.user_data.pop("awaiting_draft", None)


# ------------------------------------------------------------------ publish

def _signature() -> str:
    if db.get_setting("signature_enabled", "1") != "1":
        return ""
    return (db.get_setting("signature_text", "") or "").strip()


async def publish_draft(bot, row) -> None:
    """Publish one due draft to its channel (bot scheduled path)."""
    row = dict(row)  # sqlite3.Row → dict (supports .get for this helper)
    # Duplicate protection: never re-publish an already-published draft.
    if row.get("status") == "published":
        return

    did = row["id"]
    channel_id = row.get("channel_id")

    def _record(ok, error=None):
        attempts = row.get("attempts", 0)
        if ok:
            db.set_draft_status(did, "published")
            db.update_draft(did, published_at=db.utc_now(),
                            channel_id=channel_id, publish_error=None, attempts=0)
            db.add_publish_event(did, channel_id, "published", triggered_by="bot")
            return
        attempts += 1
        db.update_draft(did, publish_error=(error or "")[:500], attempts=attempts)
        db.add_publish_event(did, channel_id, "failed",
                             details=(error or "")[:300], triggered_by="bot")
        if attempts >= MAX_PUBLISH_ATTEMPTS:
            db.update_draft(did, status="publish_failed")

    channel = db.get_channel(channel_id) if channel_id else None
    if channel is None:
        _record(False, "کانال حذف شده؛ کانال را دوباره اضافه کن")
        return

    media_err = validate_media(row.get("media_kind"), row.get("media_path"))
    if media_err:
        _record(False, media_err)
        return

    text = (row["content"] or "").strip()
    sig = _signature()
    if sig and sig not in text:
        text = (text + "\n\n" + sig).strip()

    try:
        if row["media_path"] and Path(row["media_path"]).is_file():
            with open(row["media_path"], "rb") as fh:
                if row["media_kind"] == "video":
                    await bot.send_video(
                        chat_id=channel["chat_id"],
                        video=fh,
                        caption=text[:1024] or None,
                        supports_streaming=True,
                    )
                else:
                    await bot.send_photo(
                        chat_id=channel["chat_id"],
                        photo=fh,
                        caption=text[:1024] or None,
                    )
        else:
            await bot.send_message(
                chat_id=channel["chat_id"],
                text=text[:4096] or "…",
            )
    except Exception as exc:
        logger.warning("publish #%s failed: %s", did, exc)
        _record(False, str(exc))
        return

    _record(True)
    logger.info("published draft #%s to %s", did, channel["chat_id"])


async def publish_due(app: Application) -> None:
    for row in db.due_scheduled():
        await publish_draft(app.bot, row)


async def publisher_loop(app: Application) -> None:
    logger.info("Publisher loop started (tick=%ss).", PUBLISH_TICK)
    while True:
        try:
            await publish_due(app)
        except asyncio.CancelledError:
            logger.info("Publisher loop stopped.")
            raise
        except Exception:
            logger.exception("publisher tick failed")
        await asyncio.sleep(PUBLISH_TICK)


# ------------------------------------------------------------------ chat registry

CHAT_KIND = {"channel": "channel", "supergroup": "group", "group": "group"}


async def auto_register_chat(context, chat) -> None:
    """Register any chat the bot is in — no manual 'add channel' needed."""
    if chat is None or chat.type == "private":
        return
    try:
        kind = CHAT_KIND.get(chat.type, "group")
        db.register_chat(
            chat.id,
            chat.title or chat.username or str(chat.id),
            chat.username,
            kind,
        )
    except Exception:
        logger.exception("auto_register_chat failed for %s", chat.id)


async def startup_register(app: Application) -> None:
    """Register known chats from VOIDFEED_AUTO_CHATS (usernames / -100ids)."""
    raw = os.environ.get("VOIDFEED_AUTO_CHATS", "@FeedTheVoids")
    for ref in [r.strip() for r in raw.split(",") if r.strip()]:
        try:
            chat = await app.bot.get_chat(ref)
            await auto_register_chat(context=app, chat=chat)
            logger.info("registered chat %s (%s)", chat.id, chat.title)
        except Exception as exc:
            logger.warning("startup_register %s failed: %s", ref, exc)


async def channel_post_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    await auto_register_chat(context, update.effective_chat)


async def syncchat_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    chat = update.effective_chat
    if chat.type == "private":
        return
    if not await is_chat_admin(context, chat.id, update.effective_user.id):
        return
    await auto_register_chat(context, chat)
    kind = CHAT_KIND.get(chat.type, "group")
    await update.effective_message.reply_text(
        f"✅ چت ثبت شد: {chat.title or chat.username} ({kind})"
    )


# ------------------------------------------------------------------ moderation

_admin_cache = {}  # (chat_id, user_id) -> expiry_ts
_ban_notice_ts = {}


def _fa_minutes(minutes: int) -> str:
    if minutes >= 7 * 24 * 60:
        return "۱ هفته"
    if minutes >= 24 * 60:
        return f"{minutes // (24 * 60)} ساعت"
    return f"{minutes} دقیقه"


async def is_chat_admin(context, chat_id: int, user_id: int) -> bool:
    if user_id == context.application.bot_data.get("admin_id"):
        return True
    key = (chat_id, user_id)
    now = _time.time()
    cached = _admin_cache.get(key)
    if cached and cached > now:
        return True
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status in ("administrator", "creator"):
            _admin_cache[key] = now + 600
            return True
    except Exception:
        pass
    return False


async def _notice_and_forget(context, chat_id: int, text: str) -> None:
    try:
        sent = await context.bot.send_message(chat_id, text)
    except Exception:
        return

    async def _del():
        await asyncio.sleep(45)
        try:
            await context.bot.delete_message(chat_id, sent.message_id)
        except Exception:
            pass

    asyncio.get_running_loop().create_task(_del())


async def _report_inappropriate(
    context, chat, user, reasons: str, text: str, kind: str = "کاربر",
) -> None:
    """Send an inappropriate-content report to the owner's private chat."""
    try:
        admin_id = context.application.bot_data.get("admin_id")
        await context.bot.send_message(
            admin_id,
            f"🚨 گزارش محتوای نامناسب ({kind})\n"
            f"گروه: {chat.title or chat.id}\n"
            f"دسته: {reasons}\n"
            f"نام کاربر: {user.first_name or '—'}\n"
            f"متن: {(text or '')[:300]}",
        )
    except Exception:
        logger.warning("auto-report to admin failed", exc_info=True)


async def moderate_group_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat or not user or user.is_bot:
        return
    if db.get_setting(f"mod:{chat.id}", "1") != "1":
        return
    await auto_register_chat(context, chat)
    if await is_chat_admin(context, chat.id, user.id):
        return

    # News / channel-linked / system forwards (e.g. the bot's own news, or AI
    # posts, that a linked channel relays into the discussion group) are NEVER
    # auto-moderated — and they are ALSO out of the inappropriate-content review
    # list: admin/AI-published news goes out without review, so relayed posts
    # are skipped entirely (no filter, no report to the owner).
    is_relayed = (getattr(msg, "sender_chat", None) is not None
                  or user.id == 777000)
    if is_relayed:
        return

    mrow = db.get_mod_user(chat.id, user.id)
    if db.is_banned(mrow):
        try:
            await msg.delete()
        except Exception:
            pass
        last = _ban_notice_ts.get((chat.id, user.id), 0)
        if _time.time() - last > 300:
            _ban_notice_ts[(chat.id, user.id)] = _time.time()
            await _notice_and_forget(
                context, chat.id,
                f"⛔️ {user.first_name} در این گروه بن است؛ پیامش حذف شد.",
            )
        return

    text = msg.text or msg.caption or ""
    cats = mod.classify(text)
    if not cats:
        return

    reasons = "، ".join(mod.CAT_LABELS.get(c, c) for c in cats)
    try:
        await msg.delete()
    except Exception:
        pass

    # Automatic report: pornographic / sexual / private-body content is
    # forwarded to the owner's private chat for review (admin-only info).
    if set(cats) & mod.REPORT_CATS:
        db.log_mod_action(chat.id, user.id, "report",
                          reason=reasons, detail=(text or "")[:200])
        try:
            admin_id = context.application.bot_data.get("admin_id")
            await context.bot.send_message(
                admin_id,
                f"🚨 گزارش محتوای نامناسب\n"
                f"گروه: {chat.title or chat.id}\n"
                f"دسته: {reasons}\n"
                f"نام کاربر: {user.first_name or '—'}\n"
                f"متن: {(text or '')[:300]}",
            )
        except Exception:
            logger.warning("auto-report to admin failed", exc_info=True)

    row = db.strike_user(chat.id, user.id,
                         username=user.username, first_name=user.first_name)
    action, minutes, forever = mod.strike_action(row["warnings"])

    if action == "ban":
        db.set_ban(chat.id, user.id, forever=True,
                   username=user.username, first_name=user.first_name)
        try:
            await context.bot.ban_chat_member(chat.id, user.id)
        except Exception:
            pass
        notice = (
            f"⛔️ {user.first_name} به دلیل تکرار «{reasons}» "
            "برای همیشه از گروه بن شد."
        )
    elif action == "mute":
        until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        db.set_ban(chat.id, user.id,
                   until=until.isoformat(timespec="seconds"),
                   username=user.username, first_name=user.first_name)
        try:
            await context.bot.restrict_chat_member(
                chat.id, user.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until,
            )
        except Exception:
            pass
        notice = (
            f"🔇 {user.first_name} به دلیل «{reasons}» "
            f"{_fa_minutes(minutes)} ساکت شد (اخطار {row['warnings']})."
        )
    else:
        notice = (
            f"⚠️ {user.first_name} پیام شما به دلیل «{reasons}» حذف شد. "
            f"اخطار {row['warnings']} — بعد از ۳ اخطار بن موقت و ۶ اخطار بن دائمی."
        )

    db.log_mod_action(chat.id, user.id, action, reason=reasons,
                      detail=(text or "")[:200])
    await _notice_and_forget(context, chat.id, notice)
    logger.info("mod: chat=%s user=%s action=%s cats=%s",
                chat.id, user.id, action, cats)


async def warn_command(update, context):
    await _mod_action(update, context, "warn")


async def mute_command(update, context):
    await _mod_action(update, context, "mute")


async def ban_command(update, context):
    await _mod_action(update, context, "ban")


async def unban_command(update, context):
    await _mod_action(update, context, "unban")


async def delmsg_command(update, context):
    await _mod_action(update, context, "del")


async def kick_command(update, context):
    """Remove (kick) a user from the group without a permanent ban."""
    await _mod_action(update, context, "kick")


async def report_command(update, context):
    """Forward the replied-to message to the owner's private chat."""
    msg = update.effective_message
    chat = update.effective_chat
    if not msg or not chat:
        return
    if not await is_chat_admin(context, chat.id, update.effective_user.id):
        await msg.reply_text("این فرمان فقط برای ادمین‌ها است.")
        return
    target, replied = await _resolve_target(update, context)
    if not (msg.reply_to_message and msg.reply_to_message.from_user):
        await msg.reply_text("روی پیام موردنظر ریپلای کن: /report")
        return
    admin_id = context.application.bot_data.get("admin_id")
    who = ""
    if target is not None and getattr(target, "first_name", None):
        who = f"\nنام: {target.first_name}"
    try:
        await context.bot.copy_message(
            chat_id=admin_id, from_chat_id=chat.id,
            message_id=replied.message_id,
        )
        await msg.reply_text(
            f"✅ پیام به گزارشات فرستاده شد{who}"
        )
        db.log_mod_action(chat.id, target.id if target else None,
                          "report_manual", reason="دستی ادمین",
                          detail=(replied.text or replied.caption or "")[:200])
    except Exception as exc:
        await msg.reply_text(f"گزارش ناموفق بود: {exc}")


NEWS_TOPIC_MAP = {
    "سینما": "cinema", "فیلم": "cinema",
    "سریال": "series",
    "بازی": "games", "گیم": "games",
    "موسیقی": "music", "موزیک": "music",
    "سلبریتی": "celebs", "ستاره": "celebs", "بازیگر": "celebs",
    "شایعه": "rumor",
    "اخبار": "news", "عمومی": "news",
}

ALL_TOPIC_CATS = sorted(set(NEWS_TOPIC_MAP.values()))

_TOPIC_MSG_RE = re.compile(r"^(?:\s*#-?[\w\u0600-\u06FF_]+\s*)+$")
_URL_RE = re.compile(r"https?://\S+", re.I)


def _topics_fa_list(cats: list[str]) -> str:
    out = []
    for c in cats:
        fa = next((k for k, v in NEWS_TOPIC_MAP.items() if v == c), c)
        out.append("#" + fa)
    return " ".join(out)


async def topic_hashtags(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Direct # topic management: '#سینما' adds, '#-سینما' removes."""
    message = update.effective_message
    if not message or not is_admin(update, context):
        return
    if context.user_data and context.user_data.get("awaiting_draft"):
        return  # a hashtag can be draft text — don't hijack it
    if getattr(message, "forward_origin", None) is not None:
        return
    text = (message.text or "").strip()
    if not text or not _TOPIC_MSG_RE.fullmatch(text):
        return  # not a pure-hashtag message — leave it to other handlers
    adds: list[str] = []
    removes: list[str] = []
    for tok in text.split():
        tok = tok.lstrip("#").strip()
        neg = tok.startswith("-")
        key = tok.lstrip("-").strip()
        cat = NEWS_TOPIC_MAP.get(key)
        if not cat:
            await message.reply_text(
                "موضوع شناخته نشد: #" + key
                + "\nموضوعات ممکن: " + _topics_fa_list(ALL_TOPIC_CATS))
            return
        (removes if neg else adds).append(cat)
    current = [c for c in (db.get_setting("news_topics", "") or "").split(",") if c]
    if not current:  # "all topics" mode → make the list explicit first
        current = list(ALL_TOPIC_CATS)
    for c in removes:
        if c in current:
            current.remove(c)
    for c in adds:
        if c not in current:
            current.append(c)
    db.set_setting("news_topics", ",".join(current))
    lines = ["🏷 موضوعات فعّال: " + _topics_fa_list(current)]
    if removes:
        lines.append("🗑 حذف شد: " + _topics_fa_list(removes))
    if adds:
        lines.append("✅ اضافه شد: " + _topics_fa_list(adds))
    lines.append("بازگشت به همه: /news topic off")
    await message.reply_text("\n".join(lines))


async def submit_news(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """A news link from Johnny in the bot → instant channel post."""
    message = update.effective_message
    if not message or not is_admin(update, context):
        return
    if context.user_data and context.user_data.get("awaiting_draft"):
        return
    if getattr(message, "forward_origin", None) is not None:
        return  # forwards belong to the repost flow
    text = (message.text or "").strip()
    m = _URL_RE.search(text)
    if not m:
        return
    import newsbot
    url = m.group(0)
    topic = None
    for tok in text.split():
        if tok.startswith("#"):
            cat = NEWS_TOPIC_MAP.get(tok.lstrip("#").strip())
            if cat:
                topic = cat
                break
    await message.reply_text("🔄 در حال پردازش خبر…")
    try:
        result = await newsbot.run_manual(context.bot, url, topic)
    except Exception as exc:
        logger.exception("manual news submit failed")
        await message.reply_text(f"❌ خطا: {exc}")
        return
    if result.get("error"):
        await message.reply_text(f"❌ {result['error']}")
        return
    kind_fa = {"video": "🎬 با ویدیو", "photo": "🖼 با عکس",
               "text": "📝 فقط متن"}.get(result.get("media_kind", "text"), "")
    if result.get("published"):
        await message.reply_text(
            f"✅ خبر منتشر شد {kind_fa}\n📰 {result.get('title_fa', '')[:200]}")
    else:
        await message.reply_text(
            f"📝 پیش‌نویس #{result.get('draft_id')} ساخته شد {kind_fa}")


async def news_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """/news on|off|status|now|sched HH:MM…|topic #هاشگ‌ها."""
    message = update.effective_message
    if not message:
        return
    if not is_admin(update, context):
        await deny_access(update)
        return
    import newsbot
    args = context.args or []
    sub = args[0].lower() if args else "status"

    if sub == "on":
        db.set_setting("news_enabled", "1")
        await message.reply_text("✅ انتشار خودکار اخبار روشن شد.")
    elif sub == "off":
        db.set_setting("news_enabled", "0")
        await message.reply_text("⛔️ انتشار خودکار اخبار خاموش شد.")
    elif sub == "sched":
        rest = [a for a in args[1:] if a.strip()]
        if not rest:
            hours = newsbot._sched_slots()
            if hours:
                await message.reply_text(
                    "⏰ زمان‌بندی دستی فعّال است؛ ساعات انتشار (تهران):\n"
                    + "، ".join(hours)
                    + "\n\nتغییر: /news sched 09:00 12:30 21:00\n"
                      "بازگشت به حالت بازه‌ای: /news sched off"
                )
            else:
                await message.reply_text(
                    "حالت فعلی: بازه‌ای (هر N دقیقه).\n"
                    "زمان‌بندی دستی: /news sched 09:00 12:30 21:00"
                )
            return
        if rest[0].lower() in ("off", "خاموش", "none"):
            db.set_setting("news_sched_enabled", "0")
            await message.reply_text(
                "⏱ بازگشت به حالت بازه‌ای: "
                f"هر {newsbot._interval_min()} دقیقه یک خبر."
            )
            return
        hours = []
        for tok in rest:
            m = re.fullmatch(r"(\d{1,2}):(\d{2})", tok.strip())
            if m and int(m.group(1)) <= 23 and int(m.group(2)) <= 59:
                hours.append(f"{int(m.group(1)):02d}:{m.group(2)}")
            else:
                await message.reply_text(
                    f"فرمت «{tok}» درست نیست؛ مثل 09:00 بنویس."
                )
                return
        db.set_setting("news_sched_hours", ",".join(sorted(set(hours))))
        db.set_setting("news_sched_enabled", "1")
        await message.reply_text(
            "✅ زمان‌بندی دستی ثبت شد. انتشار فقط در این ساعات (به وقت تهران):\n"
            + "، ".join(sorted(set(hours)))
        )
    elif sub == "topic":
        rest = [a for a in args[1:] if a.strip()]
        if not rest:
            saved = db.get_setting("news_topics", "") or ""
            if saved:
                fa = [k for k, v in NEWS_TOPIC_MAP.items() if v in saved.split(",")]
                await message.reply_text(
                    "🏷 موضوعات فعّال: " + " ".join("#" + t for t in fa)
                    + "\n\nتغییر: /news topic #سینما #بازی #موسیقی\n"
                      "همه موضوعات: /news topic off"
                )
            else:
                await message.reply_text(
                    "🏷 فعلاً همه موضوعات منتشر می‌شود.\n"
                    "انتخاب: /news topic #سینما #سریال #بازی #موسیقی #سلبریتی #شایعه"
                )
            return
        if rest[0].lower() in ("off", "همه", "all", "خاموش"):
            db.set_setting("news_topics", "")
            await message.reply_text("✅ همه موضوعات فعّال شد.")
            return
        cats = []
        unknown = []
        for tok in rest:
            key = tok.lstrip("#").strip().lower()
            cat = NEWS_TOPIC_MAP.get(key) or (
                key if key in newsbot.CAT_FA else None)
            if cat and cat not in cats:
                cats.append(cat)
            else:
                unknown.append(tok)
        if not cats:
            await message.reply_text(
                "موضوع شناخته نشد. مثال: /news topic #سینما #سریال #بازی "
                "#موسیقی #سلبریتی #شایعه"
            )
            return
        db.set_setting("news_topics", ",".join(cats))
        fa_names = [newsbot.CAT_FA[c] for c in cats]
        note = (f" (ناشناخته: {' '.join(unknown)})" if unknown else "")
        await message.reply_text(
            "✅ از این بعد فقط این موضوع‌ها منتشر می‌شود: "
            + "، ".join(fa_names) + note
            + "\nهر خبر با هشتگ موضوع خودش شروع می‌شود."
        )
    elif sub == "now":
        await message.reply_text("🔄 در حال دریافت خبر…")
        try:
            result = await newsbot.run_once(bot=context.bot)
        except Exception as exc:
            logger.exception("news run_once failed")
            await message.reply_text(f"❌ خطا: {exc}")
            return
        if result.get("error"):
            await message.reply_text(f"❌ {result['error']}")
        elif result.get("published"):
            await message.reply_text(
                f"✅ منتشر شد: {result.get('title_fa', '')[:150]}"
            )
        else:
            await message.reply_text(
                f"📝 پیش‌نویس #{result.get('draft_id')} ساخته شد "
                "(انتشار خودکار خاموش است)."
            )
    else:
        enabled = db.get_setting("news_enabled", "1") == "1"
        slots = newsbot._sched_slots()
        auto = db.get_setting("news_auto_publish", "1") == "1"
        saved_topics = db.get_setting("news_topics", "") or ""
        lines = [
            f"📰 وضعیت اخبار خودکار: {'روشن' if enabled else 'خاموش'}",
        ]
        if slots:
            lines.append("زمان‌بندی دستی (تهران): " + "، ".join(slots))
        else:
            lines.append(f"بازه: هر {newsbot._interval_min()} دقیقه")
        if saved_topics:
            fa = [newsbot.CAT_FA[c] for c in saved_topics.split(",") if c in newsbot.CAT_FA]
            lines.append("موضوعات: " + "، ".join(fa))
        else:
            lines.append("موضوعات: همه")
        lines += [
            f"انتشار خودکار: {'بله' if auto else 'خیر'}",
            f"اخبار پردازش‌شده: {db.news_seen_count()}",
            f"آخرین دریافت: {db.get_setting('news_last_fetch', '') or '—'}",
        ]
        err = db.get_setting("news_last_error", "")
        if err:
            lines.append(f"آخرین خطا: {err[:200]}")
        await message.reply_text("\n".join(lines))


async def gen_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """\"/gen on|off|status|now [بخش] [جدیدترین|بهترین]|cats ...\". """
    message = update.effective_message
    if not message:
        return
    if not is_admin(update, context):
        await deny_access(update)
        return
    import contentgen
    args = context.args or []
    sub = args[0].lower() if args else "status"

    if sub == "on":
        db.set_setting("gen_enabled", "1")
        await message.reply_text(
            "✅ تولید خودکار پست (سینما/سریال/موسیقی/بازی) روشن شد."
        )
        return
    if sub == "off":
        db.set_setting("gen_enabled", "0")
        await message.reply_text("⛔️ تولید خودکار پست خاموش شد.")
        return

    if sub == "cats":
        rest = [a for a in args[1:] if a.strip()]
        if not rest:
            cur = contentgen._enabled_sections()
            fa = [contentgen.SECTIONS[c]["fa"] for c in cur]
            await message.reply_text(
                "🎯 بخش‌های تولید پست فعال:\n" + "، ".join(fa)
                + "\n\nتغییر: /gen cats سینما سریال موسیقی بازی"
            )
            return
        if rest[0].lower() in ("off", "همه", "all"):
            db.set_setting("gen_sections",
                           ",".join(contentgen.DEFAULT_SECTIONS))
            await message.reply_text("✅ همه بخش‌ها فعال شد.")
            return
        cats, unknown = [], []
        for tok in rest:
            key = tok.lstrip("#").strip()
            cat = contentgen.GEN_CAT_MAP.get(key) or (
                key if key in contentgen.SECTIONS else None)
            if cat and cat not in cats:
                cats.append(cat)
            else:
                unknown.append(tok)
        if not cats:
            await message.reply_text(
                "بخش شناخته نشد. مثال: /gen cats سینما سریال موسیقی بازی")
            return
        db.set_setting("gen_sections", ",".join(cats))
        fa = [contentgen.SECTIONS[c]["fa"] for c in cats]
        note = (f" (ناشناخته: {' '.join(unknown)})" if unknown else "")
        await message.reply_text(
            "✅ از این بعد فقط این بخش‌ها تولید می‌شود: "
            + "، ".join(fa) + note
        )
        return

    if sub == "now":
        rest = args[1:]
        section = None
        kind = None
        for tok in rest:
            key = tok.lstrip("#").strip()
            cat = contentgen.GEN_CAT_MAP.get(key) or (
                key if key in contentgen.SECTIONS else None)
            low = tok.lower()
            if cat and section is None:
                section = cat
            elif low in ("newest", "جدیدترین"):
                kind = "newest"
            elif low in ("best", "بهترین"):
                kind = "best"
        await message.reply_text(
            "🔄 در حال تولید پست… (ممکن است تا یک دقیقه طول بکشد)")
        try:
            result = await contentgen.run_once(
                context.bot, section=section, kind=kind)
        except Exception as exc:
            logger.exception("contentgen now failed")
            await message.reply_text(f"❌ خطا: {exc}")
            return
        if result.get("error"):
            await message.reply_text(f"❌ {result['error']}")
            return
        if result.get("published"):
            await message.reply_text(
                "✅ پست تولید و منتشر شد."
                + (f"\n📌 {result['title']}" if result.get("title") else ""))
        else:
            await message.reply_text(
                f"📝 پیش‌نویس #{result.get('draft_id')} ساخته شد "
                "(انتشار ناموفق).")
        return

    # status (default)
    enabled = db.get_setting("gen_enabled", "1") == "1"
    secs = contentgen._enabled_sections()
    fa = [contentgen.SECTIONS[c]["fa"] for c in secs]
    lines = [
        "🎬 وضعیت تولید پست (سینما/سریال/موسیقی/بازی): "
        + ("روشن" if enabled else "خاموش"),
        f"بازه: هر {contentgen._interval_min()} دقیقه",
        "بخش‌ها: " + "، ".join(fa),
    ]
    last_title = db.get_setting("gen_last_title", "")
    if last_title:
        lines.append("آخرین پست: " + last_title[:150])
    last_at = db.get_setting("gen_last_at", "")
    if last_at:
        lines.append("زمان آخرین پست: " + last_at)
    err = db.get_setting("gen_last_error", "")
    if err:
        lines.append("آخرین خطا: " + err[:200])
    lines.append("\nدستی: /gen now [بخش] [جدیدترین|بهترین]")
    await message.reply_text("\n".join(lines))


async def _resolve_target(update, context):
    """Target = replied-to user, or user_id argument."""
    msg = update.effective_message
    if msg and msg.reply_to_message and msg.reply_to_message.from_user:
        return msg.reply_to_message.from_user, msg.reply_to_message
    args = context.args or []
    if args and args[-1].lstrip("-").isdigit():
        chat = await context.bot.get_chat(int(args[-1]))
        return chat, msg
    return None, msg


async def _mod_action(update, context, action: str) -> None:
    msg = update.effective_message
    chat = update.effective_chat
    if not msg or not chat:
        return
    if not await is_chat_admin(context, chat.id, update.effective_user.id):
        await msg.reply_text("این فرمان فقط برای ادمین‌ها است.")
        return

    target, replied = await _resolve_target(update, context)
    if target is None:
        hints = {
            "warn": "روی پیام کاربر ریپلای کن: /warn",
            "mute": "روی پیام کاربر ریپلای کن: /mute 60 (دقیقه)",
            "ban": "روی پیام کاربر ریپلای کن: /ban",
            "unban": "روی پیام کاربر ریپلای کن یا: /unban 123456789",
            "kick": "روی پیام کاربر ریپلای کن: /kick",
            "report": "روی پیام موردنظر ریپلای کن: /report",
            "del": "روی پیام موردنظر ریپلای کن: /del",
        }
        await msg.reply_text(hints.get(action, "هدف مشخص نیست."))
        return

    uid = target.id
    name = target.first_name or (target.username and "@" + target.username) or str(uid)

    if action == "warn":
        row = db.strike_user(chat.id, uid, username=target.username,
                             first_name=target.first_name)
        db.log_mod_action(chat.id, uid, "warn", reason="دستی ادمین")
        await msg.reply_text(
            f"⚠️ به {name} اخطار دستی داده شد (مجموع اخطارها: {row['warnings']})."
        )
    elif action == "mute":
        minutes = 60
        args = [a for a in (context.args or []) if a.isdigit()]
        if args:
            minutes = max(1, int(args[0]))
        until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        db.set_ban(chat.id, uid, until=until.isoformat(timespec="seconds"),
                   username=target.username, first_name=target.first_name)
        try:
            await context.bot.restrict_chat_member(
                chat.id, uid,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until,
            )
        except Exception as exc:
            await msg.reply_text(f"محدودسازی در تلگرام ناموفق بود: {exc}")
            return
        db.log_mod_action(chat.id, uid, "mute", reason="دستی ادمین",
                          detail=f"{minutes}m")
        await msg.reply_text(f"🔇 {name} برای {_fa_minutes(minutes)} ساکت شد.")
    elif action == "ban":
        db.set_ban(chat.id, uid, forever=True,
                   username=target.username, first_name=target.first_name)
        try:
            await context.bot.ban_chat_member(chat.id, uid)
        except Exception as exc:
            await msg.reply_text(f"بن در تلگرام ناموفق بود: {exc}")
            return
        db.log_mod_action(chat.id, uid, "ban", reason="دستی ادمین")
        await msg.reply_text(f"⛔️ {name} برای همیشه بن شد.")
    elif action == "unban":
        db.unban_user(chat.id, uid)
        try:
            await context.bot.unban_chat_member(chat.id, uid, only_if_banned=True)
        except Exception:
            pass
        db.log_mod_action(chat.id, uid, "unban", reason="دستی ادمین")
        await msg.reply_text(f"✅ {name} آنبن شد و اخطارهایش پاک شد.")
    elif action == "kick":
        try:
            await context.bot.ban_chat_member(chat.id, uid)
            await context.bot.unban_chat_member(chat.id, uid)
        except Exception as exc:
            await msg.reply_text(f"حذف کاربر ناموفق بود: {exc}")
            return
        db.log_mod_action(chat.id, uid, "kick", reason="دستی ادمین")
        await msg.reply_text(f"👋 {name} از گروه حذف شد (بدون بن).")
    elif action == "del":
        if replied:
            try:
                await replied.delete()
                db.log_mod_action(chat.id, uid, "delete", reason="دستی ادمین")
                await msg.reply_text("پیام حذف شد.")
            except Exception as exc:
                await msg.reply_text(f"حذف ناموفق: {exc}")
        else:
            await msg.reply_text("روی پیام موردنظر ریپلای کن: /del")


async def mod_toggle_command(update, context):
    msg = update.effective_message
    chat = update.effective_chat
    if not msg or not chat:
        return
    if not await is_chat_admin(context, chat.id, update.effective_user.id):
        await msg.reply_text("این فرمان فقط برای ادمین‌ها است.")
        return
    arg = " ".join(context.args).strip().lower()
    if arg in ("off", "خاموش", "0"):
        db.set_setting(f"mod:{chat.id}", "0")
        await msg.reply_text("ناظر چت در این گروه خاموش شد.")
    elif arg in ("on", "روشن", "1", ""):
        db.set_setting(f"mod:{chat.id}", "1")
        await msg.reply_text("ناظر چت در این گروه روشن شد.")
    else:
        await msg.reply_text("فرمت: /mod on یا /mod off")


async def modstats_command(update, context):
    msg = update.effective_message
    chat = update.effective_chat
    if not msg or not chat:
        return
    if not await is_chat_admin(context, chat.id, update.effective_user.id):
        await msg.reply_text("این فرمان فقط برای ادمین‌ها است.")
        return
    s = db.mod_stats(chat.id)
    enabled = db.get_setting(f"mod:{chat.id}", "1") == "1"
    await msg.reply_text(
        f"وضعیت ناظر: {'روشن' if enabled else 'خاموش'}\n"
        f"کاربران اخطارگرفته: {s['warned']}\n"
        f"در حال حاضر بن: {s['banned']}\n"
        f"کل اقدام‌ها: {s['actions']}\n\n"
        "فرمان‌ها: /warn /mute 60 /ban /unban /del /mod on|off"
    )


HELP_TEXT = (
    "راهنمای VoidFeed\n\n"
    "/menu — باز کردن منوی اصلی (دکمه‌ای).\n"
    "/lang en|fa — تغییر زبان بات.\n"
    "/studio — استودیوی وب (مینی‌اپ) داخل تلگرام.\n"
    "/draft — شروع ساخت پیشنویس؛ سپس متن را ارسال کن.\n"
    "/draft متن — ساخت پیشنویس با متن مستقیم.\n"
    "/queue — حداکثر ۱۰ پیشنویس اخیر.\n"
    "/approve ID — تأیید پیشنویس.\n"
    "/reject ID — رد پیشنویس.\n"
    "/publish ID — انتشار فوری در کانال.\n"
    "/cancel ID — لغو زمانبندی پست.\n"
    "/delete ID — حذف پیشنویس.\n"
    "/channels — فهرست کانالها.\n\n"
    "🤖 هوش مصنوعی (رایگان، بدون کلید):\n"
    "/ai <سؤال> — چت با AI (فارسی و انگلیسی)\n"
    "/draw <پرامپت انگلیسی> — ساخت تصویر با AI\n"
    "/gen — تولید پست معرفی با AI (جدیدترین/بهترین)\n"
    "/gen now [بخش] [جدیدترین|بهترین] — تولید و انتشار فوری\n"
    "/gen on|off — روشن/خاموش تولید خودکار\n"
    "/gen cats سینما سریال موسیقی بازی — انتخاب بخشها\n"
    "بخشها: فیلمها، سریالها، موسیقی متن، موزیسینها و خوانندگان، "
    "و بازیهای PC/کنسول/موبایل.\n\n"
    "زمانبندی و انتشار تصویری از داخل استودیو انجام میشود.\n"
    "فوروارد پست از کانالهای دیگر = پیشنویس خودکار (متن و تصویر).\n"
    "پیشنویسها در SQLite ذخیره میشوند.\n\n"
    "🛡 ناظر چت (گروهها):\n"
    "پیامهای حاوی فحش/محتوای جنسی/پورنوگرافی/اشاره به اعضای خصوصی/"
    "بحث سیاسی/محتوای غیراخلاقی حذف و اخطار ثبت میشود؛ "
    "۳ اخطار = سکوت ۱ ساعت، ۴ = ۲۴ ساعت، ۵ = ۱ هفته، ۶ = بن دائمی.\n"
    "محتوای پورنو/جنسی/اعضای خصوصی خودکار به گزارشات (چت خصوصی تو) ارسال میشود.\n"
    "حریم خصوصی: اطلاعات خصوصی کاربران (آیدی/یوزرنیم) فقط برای ادمینها قابل مشاهده است.\n"
    "فرمانهای ادمین گروه: /warn /mute 60 /ban /unban /kick /report /del — "
    "روی پیام کاربر ریپلای کن.\n"
    "/mod on|off — خاموش/روشن کردن ناظر؛ /modstats — آمار.\n\n"
    "📰 اخبار خودکار:\n"
    "/news on|off — کل انتشار خودکار.\n"
    "/news sched 09:00 12:30 21:00 — انتشار فقط در ساعات مشخص (به وقت تهران).\n"
    "/news sched off — بازگشت به حالت بازهای (هر N دقیقه).\n"
    "/news topic #سینما #سریال #بازی #موسیقی #سلبریتی #شایعه — فقط این موضوعها؛\n"
    "هر خبر با هشتگ موضوعش شروع میشود (#سینما و…). /news topic off = همه.\n"
    "#نام — اضافه مستقیم موضوع؛ #-نام — حذف آن (فقط خود هشتگ را بفرست).\n"
    "لینک خبر را مستقیم بفرست → ترجمه، رسانه و انتشار در کانال خودکار است؛\n"
    "اگر خبر ویدیوی کوتاه داشته باشد، ویدیو منتشر میشود نه عکس؛ در غیر این صورت\n"
    "لینک ویدیوی یوتیوب/امبد مقاله به کپشن اضافه میشود.\n"
    "/news now — دریافت و انتشار فوری یک خبر.\n"
    "/news status — وضعیت کامل.\n"
    "همه خبرها فارسی منتشر میشوند؛ نامهای خاص (فیل/سریال/هنرمند/بازی) به زبان اصلی\n"
    "میمانند و فقط در صورت وجود ترجمه رسمی جاافتاده ترجمه میشوند.\n"
)


HELP_TEXT_EN = (
    "VoidFeed help\n\n"
    "/menu — open the main (button) menu.\n"
    "/studio — open the Studio web app inside Telegram.\n"
    "/draft — start a new draft; then send the text.\n"
    "/draft text — create a draft directly from text.\n"
    "/queue — latest drafts (up to 10).\n"
    "/approve ID — approve a draft.\n"
    "/reject ID — reject a draft.\n"
    "/publish ID — publish immediately to the channel.\n"
    "/cancel ID — cancel a scheduled post.\n"
    "/delete ID — delete a draft.\n"
    "/channels — list registered channels.\n"
    "/lang en|fa — switch bot language.\n\n"
    "🤖 AI (free, no key):\n"
    "/ai <question> — chat with AI (FA/EN)\n"
    "/draw <english prompt> — generate an image with AI\n"
    "/gen — generate an intro post (newest/best)\n"
    "/gen now [section] [newest|best] — generate & publish now\n"
    "/gen on|off — toggle automatic generation\n"
    "/gen cats cinema series music games — choose sections\n"
    "Sections: movies, series, soundtracks, musicians & singers, "
    "and PC/console/mobile games.\n\n"
    "Scheduling and visual publishing happen from the Studio.\n"
    "Forwarding posts from other channels = automatic draft (text + media).\n"
    "Drafts are stored in SQLite.\n\n"
    "🛡 Chat moderator (groups):\n"
    "Messages with profanity/sexual/porn/body-parts/political/immoral "
    "content are deleted and warned; 3 warnings = 1h mute, 4 = 24h, "
    "5 = 1 week, 6 = permanent ban.\n"
    "Porn/sexual/body content is auto-reported to your private chat.\n"
    "Group admin commands (reply to the user's message): "
    "/warn /mute 60 /ban /unban /kick /report /del.\n"
    "/mod on|off — toggle moderator; /modstats — stats.\n\n"
    "📰 Auto news:\n"
    "/news on|off — toggle auto publishing.\n"
    "/news sched 09:00 12:30 21:00 — publish only at these hours (Tehran).\n"
    "/news sched off — back to interval mode (every N minutes).\n"
    "/news topic #سینما #سریال #بازی #موسیقی #سلبریتی #شایعه — only these topics;\n"
    "each news starts with its topic hashtag (#سینما etc.). /news topic off = all.\n"
    "Send a news link directly → translation, media and publishing are automatic;\n"
    "if the item has a short video it publishes as video, otherwise the article's\n"
    "YouTube/embed video link is appended to the caption.\n"
    "/news now — fetch and publish one news item right now.\n"
    "/news status — full status.\n"
    "All news is published in natural Persian; proper nouns (film/series/artist/game)\n"
    "stay in the original language and are translated only when an official,\n"
    "established Persian title exists.\n"
)


def _menu_main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(tr("mn_news"), callback_data="menu:news"),
         InlineKeyboardButton(tr("mn_gen"), callback_data="menu:gen")],
        [InlineKeyboardButton(tr("mn_drafts"), callback_data="menu:drafts")],
        [InlineKeyboardButton(tr("mn_help"), callback_data="menu:help")],
    ])


def _menu_back_kb():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(tr("back_main"), callback_data="menu:main")
    ]])


def _menu_news_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 " + tr("status_label"), callback_data="act:news:status")],
        [InlineKeyboardButton("✅ " + tr("on_str"), callback_data="act:news:on"),
         InlineKeyboardButton("⛔️ " + tr("off_str"), callback_data="act:news:off")],
        [InlineKeyboardButton("⚡️ " + tr("published_news").format(t="now"),
                              callback_data="act:news:now")],
        [InlineKeyboardButton("⏰ " + tr("sched_label"), callback_data="act:news:sched")],
        [InlineKeyboardButton(tr("back"), callback_data="menu:main")],
    ])


def _menu_gen_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 " + tr("mn_cinema"), callback_data="act:gen:now:cinema"),
         InlineKeyboardButton("📺 " + tr("mn_series"), callback_data="act:gen:now:series")],
        [InlineKeyboardButton("🎵 " + tr("mn_music"), callback_data="act:gen:now:music"),
         InlineKeyboardButton("🕹 " + tr("mn_games"), callback_data="act:gen:now:games")],
        [InlineKeyboardButton("🔀 " + tr("gen_next"), callback_data="act:gen:now")],
        [InlineKeyboardButton("📊 " + tr("status_label"), callback_data="act:gen:status")],
        [InlineKeyboardButton("✅ " + tr("on_str"), callback_data="act:gen:on"),
         InlineKeyboardButton("⛔️ " + tr("off_str"), callback_data="act:gen:off")],
        [InlineKeyboardButton(tr("back"), callback_data="menu:main")],
    ])


def _menu_drafts_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 " + tr("drafts_q"), callback_data="act:drafts:queue")],
        [InlineKeyboardButton("❓ " + tr("drafts_help_label"), callback_data="act:drafts:help")],
        [InlineKeyboardButton(tr("back"), callback_data="menu:main")],
    ])


def _news_status_text(newsbot) -> str:
    enabled = db.get_setting("news_enabled", "1") == "1"
    slots = newsbot._sched_slots()
    auto = db.get_setting("news_auto_publish", "1") == "1"
    saved = db.get_setting("news_topics", "") or ""
    lines = [tr("st_news").format(s=tr("on_str") if enabled else tr("off_str"))]
    if slots:
        lines.append(tr("sched_label") + ": " + "، ".join(slots))
    else:
        lines.append(tr("interval").format(n=newsbot._interval_min()))
    if saved:
        fa = [newsbot.CAT_FA[c] for c in saved.split(",") if c in newsbot.CAT_FA]
        lines.append(tr("topics").format(t="، ".join(fa)))
    else:
        lines.append(tr("topics").format(t=tr("topics_all")))
    lines += [
        tr("auto_pub").format(v=tr("yes") if auto else tr("no")),
        tr("processed").format(n=db.news_seen_count()),
    ]
    err = db.get_setting("news_last_error", "")
    if err:
        lines.append(tr("last_err").format(e=err[:200]))
    return "\n".join(lines)


def _gen_status_text(contentgen) -> str:
    enabled = db.get_setting("gen_enabled", "1") == "1"
    secs = contentgen._enabled_sections()
    fa = [contentgen.SECTIONS[c]["fa"] for c in secs]
    lines = [
        tr("st_gen").format(s=tr("on_str") if enabled else tr("off_str")),
        tr("interval").format(n=contentgen._interval_min()),
        tr("sections").format(l="، ".join(fa)),
    ]
    title = db.get_setting("gen_last_title", "")
    if title:
        lines.append(tr("last_post").format(t=title[:150]))
    err = db.get_setting("gen_last_error", "")
    if err:
        lines.append(tr("last_err").format(e=err[:200]))
    return "\n".join(lines)


async def _cb_news(q, data: str, context) -> None:
    act = data.split(":", 2)[-1]
    import newsbot
    if act == "on":
        db.set_setting("news_enabled", "1")
        await q.edit_message_text(tr("on_news"),
                                  reply_markup=_menu_news_kb())
    elif act == "off":
        db.set_setting("news_enabled", "0")
        await q.edit_message_text(tr("off_news"),
                                  reply_markup=_menu_news_kb())
    elif act == "status":
        await q.edit_message_text(_news_status_text(newsbot),
                                  reply_markup=_menu_news_kb())
    elif act == "sched":
        await q.edit_message_text(tr("sched_info"),
                                  reply_markup=_menu_news_kb())
    elif act == "now":
        await q.edit_message_text(tr("working_news"),
                                  reply_markup=_menu_news_kb())
        try:
            result = await newsbot.run_once(bot=context.bot)
        except Exception as exc:
            await q.edit_message_text(tr("err_fmt").format(e=exc),
                                      reply_markup=_menu_news_kb())
            return
        if result.get("error"):
            txt = tr("err_fmt").format(e=result["error"])
        elif result.get("published"):
            txt = tr("published_news").format(t=result.get("title_fa", "")[:150])
        else:
            txt = tr("draft_news").format(id=result.get("draft_id"))
        await q.edit_message_text(txt, reply_markup=_menu_news_kb())


async def _cb_gen(q, data: str, context) -> None:
    parts = data.split(":")
    act = parts[2] if len(parts) > 2 else ""
    import contentgen
    if act == "on":
        db.set_setting("gen_enabled", "1")
        await q.edit_message_text(tr("on_gen"),
                                  reply_markup=_menu_gen_kb())
    elif act == "off":
        db.set_setting("gen_enabled", "0")
        await q.edit_message_text(tr("off_gen"),
                                  reply_markup=_menu_gen_kb())
    elif act == "status":
        await q.edit_message_text(_gen_status_text(contentgen),
                                  reply_markup=_menu_gen_kb())
    elif act == "now":
        section = parts[3] if len(parts) > 3 else None
        if section and section not in contentgen.SECTIONS:
            section = None
        await q.edit_message_text(tr("working_gen"),
                                  reply_markup=_menu_gen_kb())
        try:
            result = await contentgen.run_once(context.bot, section=section)
        except Exception as exc:
            await q.edit_message_text(tr("err_fmt").format(e=exc),
                                      reply_markup=_menu_gen_kb())
            return
        if result.get("error"):
            txt = tr("err_fmt").format(e=result["error"])
        elif result.get("published"):
            txt = tr("published_gen") + (
                f"\n📌 {result['title']}" if result.get("title") else "")
        else:
            txt = tr("draft_gen").format(id=result.get("draft_id"))
        await q.edit_message_text(txt, reply_markup=_menu_gen_kb())


async def _cb_drafts(q, data: str) -> None:
    act = data.split(":", 2)[-1]
    if act == "queue":
        drafts = db.list_drafts(limit=10)
        if not drafts:
            txt = tr("queue_empty")
        else:
            labels = {
                "draft": "در انتظار بررسی", "approved": "تأییدشده",
                "rejected": "ردشده", "scheduled": "زمان‌بندی‌شده",
                "published": "منتشرشده", "publish_failed": "انتشار ناموفق",
            }
            lines = [tr("queue_title")]
            for d in drafts:
                preview = re.sub(r"\s+", " ", d["content"] or "(تصویر)").strip()
                if len(preview) > 100:
                    preview = preview[:97] + "..."
                lines.append(f"\n#{d['id']} — {labels.get(d['status'], d['status'])}\n{preview}")
            txt = "\n".join(lines)
        await q.edit_message_text(txt, reply_markup=_menu_drafts_kb())
    elif act == "help":
        await q.edit_message_text(tr("drafts_manage"),
                                  reply_markup=_menu_drafts_kb())


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not q:
        return
    admin_id = context.application.bot_data.get("admin_id")
    if q.from_user is None or q.from_user.id != admin_id:
        await q.answer("دسترسی مجاز نیست.", show_alert=True)
        return
    await q.answer()
    data = q.data or ""
    if q.message is None:
        return

    if data == "menu:main":
        await q.edit_message_text(tr("hello"),
                                  reply_markup=_menu_main_kb())
        return
    if data == "menu:news":
        await q.edit_message_text(tr("news_title"), reply_markup=_menu_news_kb())
        return
    if data == "menu:gen":
        await q.edit_message_text(tr("gen_title"), reply_markup=_menu_gen_kb())
        return
    if data == "menu:drafts":
        await q.edit_message_text(tr("drafts_title"), reply_markup=_menu_drafts_kb())
        return
    if data == "menu:help":
        await q.edit_message_text(_help_text(), reply_markup=_menu_back_kb())
        return

    if data.startswith("act:news:"):
        await _cb_news(q, data, context)
        return
    if data.startswith("act:gen:"):
        await _cb_gen(q, data, context)
        return
    if data.startswith("act:drafts:"):
        await _cb_drafts(q, data)
        return


# ------------------------------------------------------------------ commands

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Alias for /start — re-opens the inline main menu anytime."""
    await start(update, context)


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    clear_pending(context)
    message = update.effective_message
    if not message:
        return
    if not is_admin(update, context):
        await deny_access(update)
        return

    keyboard = _menu_main_kb()
    await message.reply_text(tr("hello"), reply_markup=keyboard)


def _help_text() -> str:
    return HELP_TEXT_EN if _lang() == "en" else HELP_TEXT


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    clear_pending(context)
    message = update.effective_message
    if not message:
        return
    if not is_admin(update, context):
        await deny_access(update)
        return

    await message.reply_text(_help_text())


async def lang_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Language toggle: /lang en | /lang fa | /lang (status)."""
    message = update.effective_message
    if not message:
        return
    if not is_admin(update, context):
        await deny_access(update)
        return
    args = context.args or []
    if not args:
        await message.reply_text(tr("lang_done").format(l=_lang()))
        return
    want = (args[0] or "").strip().lower()
    if want not in T and want not in ("fa", "en"):
        # allow full names
        want = {"persian": "fa", "farsi": "fa", "english": "en"}.get(want, want)
    if want not in ("fa", "en"):
        await message.reply_text(tr("lang_usage"))
        return
    db.set_setting("lang", want)
    await message.reply_text(tr("lang_done").format(l=want))


async def studio_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    clear_pending(context)
    message = update.effective_message
    if not message:
        return
    if not is_admin(update, context):
        await deny_access(update)
        return

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🌌 باز کردن استودیو", web_app=WebAppInfo(url=STUDIO_URL))
    ]])
    await message.reply_text(
        "استودیوی تولید محتوا:\n"
        "• ساخت و ویرایش پست با تصویر\n"
        "• زمان‌بندی انتشار با تقویم\n"
        "• تولید و بازنویسی با هوش مصنوعی\n"
        "• مدیریت کانال‌ها و امضا",
        reply_markup=keyboard,
    )


async def draft_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    message = update.effective_message
    if not message:
        return
    if not is_admin(update, context):
        clear_pending(context)
        await deny_access(update)
        return

    content = " ".join(context.args).strip()
    if content:
        clear_pending(context)
        if len(content) > MAX_DRAFT_LENGTH:
            await message.reply_text(
                f"متن بیش از حد طولانی است. حداکثر {MAX_DRAFT_LENGTH} نویسه مجاز است."
            )
            return
        draft_id = db.save_draft(content, source="bot")
        await message.reply_text(
            f"پیش‌نویس شمارهٔ {draft_id} ذخیره شد.\n"
            "وضعیت: در انتظار بررسی\n"
            f"برای تأیید: /approve {draft_id}\n"
            f"برای رد: /reject {draft_id}"
        )
        return

    if context.user_data is None:
        await message.reply_text(
            "ساخت پیش‌نویس در این نوع گفتگو ممکن نیست؛ "
            "لطفاً در گفت‌وگوی خصوصی با بات تلاش کن."
        )
        return
    context.user_data["awaiting_draft"] = True
    await message.reply_text(
        "متن پیش‌نویس را در پیام بعدی بفرست.\n"
        "برای لغو، یکی از فرمان‌های بات مثل /help را بفرست."
    )


async def receive_draft(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if context.user_data is None:
        return

    message = update.effective_message
    if not message:
        return

    if not is_admin(update, context):
        clear_pending(context)
        # The bot acts as a chat supervisor even in private chats:
        # dirty messages from strangers are recorded and warned.
        text = (message.text or "").strip()
        cats = mod.classify(text)
        if cats:
            reasons = "، ".join(mod.CAT_LABELS.get(c, c) for c in cats)
            row = db.strike_user(message.chat_id, update.effective_user.id,
                                 username=update.effective_user.username,
                                 first_name=update.effective_user.first_name)
            db.log_mod_action(message.chat_id, update.effective_user.id,
                              "warn_private", reason=reasons, detail=text[:200])
            await message.reply_text(
                f"⚠️ {update.effective_user.first_name} پیام نامناسب («{reasons}») "
                f"ثبت شد. اخطار {row['warnings']} — ادامهٔ ارسال محتوای نامناسب "
                "منجر به مسدودسازی دسترسی شما می‌شود."
            )
        return

    # Forwarded posts become drafts automatically (repost flow).
    if getattr(message, "forward_origin", None) is not None:
        await save_forward(update, context)
        return

    if not context.user_data.get("awaiting_draft"):
        return

    content = (message.text or "").strip()
    if not content:
        await message.reply_text("متن خالی است؛ لطفاً متن پیش‌نویس را بفرست.")
        return

    if len(content) > MAX_DRAFT_LENGTH:
        await message.reply_text(
            f"متن بیش از حد طولانی است. حداکثر {MAX_DRAFT_LENGTH} نویسه مجاز است."
        )
        return

    clear_pending(context)
    draft_id = db.save_draft(content, source="bot")
    await message.reply_text(
        f"پیش‌نویس شمارهٔ {draft_id} ذخیره شد.\n"
        "وضعیت: در انتظار بررسی\n"
        f"برای تأیید: /approve {draft_id}\n"
        f"برای رد: /reject {draft_id}"
    )


async def receive_photo_forward(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Forwarded photos (with or without caption) become drafts."""
    if context.user_data is None:
        return
    message = update.effective_message
    if not message:
        return
    if not is_admin(update, context):
        clear_pending(context)
        return
    if getattr(message, "forward_origin", None) is None:
        if not context.user_data.get("awaiting_draft"):
            return
        await message.reply_text(
            "برای پیوست عکس به پیش‌نویس، از استودیو (/studio) استفاده کن."
        )
        return
    await save_forward(update, context)


async def save_forward(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Repost flow: forwarded message (text/photo) becomes a draft."""
    message = update.effective_message
    caption = (message.caption or message.text or "").strip()
    media_path = None

    if message.photo:
        try:
            tg_file = await message.photo[-1].get_file()
            name = f"fw_{int(message.message_id)}_{secrets.token_hex(4)}.jpg"
            path = db.MEDIA_DIR / name
            await tg_file.download_to_drive(str(path))
            os.chmod(path, 0o600)
            media_path = str(path)
        except Exception as exc:
            logger.warning("forward photo download failed: %s", exc)
    elif message.video:
        try:
            tg_file = await message.video.get_file()
            name = f"fw_{int(message.message_id)}_{secrets.token_hex(4)}.mp4"
            path = db.MEDIA_DIR / name
            await tg_file.download_to_drive(str(path))
            os.chmod(path, 0o600)
            media_path = str(path)
        except Exception as exc:
            logger.warning("forward video download failed: %s", exc)

    if not caption and not media_path:
        await message.reply_text(
            "این نوع فوروارد قابل تبدیل به پیش‌نویس نیست (فقط متن، عکس و ویدیو)."
        )
        return

    if len(caption) > MAX_DRAFT_LENGTH:
        caption = caption[:MAX_DRAFT_LENGTH]

    kind = "video" if (media_path and media_path.endswith(".mp4")) else "photo"
    draft_id = db.save_draft(
        caption, media_path=media_path,
        media_kind=kind if media_path else None, source="forward",
    )
    await message.reply_text(
        f"پیش‌نویس شمارهٔ {draft_id} از فوروارد ساخته شد.\n"
        f"برای مدیریت: /studio یا /approve {draft_id}"
    )


async def queue_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    clear_pending(context)
    message = update.effective_message
    if not message:
        return
    if not is_admin(update, context):
        await deny_access(update)
        return

    drafts = db.list_drafts(limit=QUEUE_LIMIT)
    if not drafts:
        await message.reply_text("هنوز پیش‌نویسی ثبت نشده است. با /draft شروع کن.")
        return

    status_labels = {
        "draft": "در انتظار بررسی",
        "approved": "تأییدشده",
        "rejected": "ردشده",
        "scheduled": "زمان‌بندی‌شده",
        "published": "منتشرشده",
        "publish_failed": "انتشار ناموفق",
    }

    lines = ["فهرست پیش‌نویس‌ها (حداکثر ۱۰ مورد):"]
    for draft in drafts:
        preview = re.sub(r"\s+", " ", draft["content"] or "(تصویر)").strip()
        if len(preview) > 140:
            preview = preview[:137] + "..."
        extra = ""
        if draft["scheduled_at"]:
            extra = f" | زمان: {draft['scheduled_at']}"
        lines.append(
            f"\n#{draft['id']} — {status_labels.get(draft['status'], draft['status'])}{extra}\n{preview}"
        )

    result = "\n".join(lines)
    for offset in range(0, len(result), 3500):
        await message.reply_text(result[offset:offset + 3500])


async def review_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    new_status: str,
) -> None:
    clear_pending(context)
    message = update.effective_message
    if not message:
        return
    if not is_admin(update, context):
        await deny_access(update)
        return

    if len(context.args) != 1 or not context.args[0].isdigit():
        command = "/approve ID" if new_status == "approved" else "/reject ID"
        await message.reply_text(f"فرمت درست: {command}")
        return

    draft_id = int(context.args[0])
    if draft_id < 1:
        await message.reply_text("شناسهٔ پیش‌نویس معتبر نیست.")
        return

    result = db.set_draft_status(
        draft_id, new_status,
        admin_id=update.effective_user.id,
    )

    if result == "not_found":
        await message.reply_text(f"پیش‌نویس شمارهٔ {draft_id} پیدا نشد.")
    elif new_status == "approved":
        await message.reply_text(
            f"پیش‌نویس شمارهٔ {draft_id} تأیید شد.\n"
            "برای انتشار: /studio یا /publish " + str(draft_id)
        )
    else:
        await message.reply_text(f"پیش‌نویس شمارهٔ {draft_id} رد شد.")


async def approve_command(update, context):
    await review_command(update, context, "approved")


async def reject_command(update, context):
    await review_command(update, context, "rejected")


async def publish_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    clear_pending(context)
    message = update.effective_message
    if not message:
        return
    if not is_admin(update, context):
        await deny_access(update)
        return

    if len(context.args) != 1 or not context.args[0].isdigit():
        await message.reply_text("فرمت درست: /publish ID")
        return

    draft_id = int(context.args[0])
    row = db.get_draft(draft_id)
    if not row:
        await message.reply_text(f"پیش‌نویس شمارهٔ {draft_id} پیدا نشد.")
        return
    if row["status"] == "published":
        await message.reply_text("این پست قبلاً منتشر شده است.")
        return
    if not row["channel_id"]:
        default = db.get_default_channel()
        if not default:
            await message.reply_text(
                "هنوز کانالی ثبت نشده است. از استودیو (/studio) کانال اضافه کن."
            )
            return
        db.update_draft(draft_id, channel_id=default["id"])
        row = db.get_draft(draft_id)

    await message.reply_text(f"در حال انتشار پست {draft_id}…")
    await publish_draft(context.bot, row)
    row = db.get_draft(draft_id)
    if row["status"] == "published":
        await message.reply_text("پست منتشر شد ✓")
    else:
        await message.reply_text(
            f"انتشار ناموفق بود: {row['publish_error'] or 'خطای نامشخص'}"
        )


async def cancel_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    clear_pending(context)
    message = update.effective_message
    if not message:
        return
    if not is_admin(update, context):
        await deny_access(update)
        return

    if len(context.args) != 1 or not context.args[0].isdigit():
        await message.reply_text("فرمت درست: /cancel ID")
        return

    draft_id = int(context.args[0])
    row = db.get_draft(draft_id)
    if not row:
        await message.reply_text(f"پیش‌نویس شمارهٔ {draft_id} پیدا نشد.")
        return
    if row["status"] != "scheduled":
        await message.reply_text("این پیش‌نویس زمان‌بندی نشده است.")
        return
    db.set_draft_status(draft_id, "approved", admin_id=update.effective_user.id)
    await message.reply_text("زمان‌بندی لغو شد؛ وضعیت: تأییدشده.")


async def delete_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    clear_pending(context)
    message = update.effective_message
    if not message:
        return
    if not is_admin(update, context):
        await deny_access(update)
        return

    if len(context.args) != 1 or not context.args[0].isdigit():
        await message.reply_text("فرمت درست: /delete ID")
        return

    draft_id = int(context.args[0])
    if db.delete_draft(draft_id):
        await message.reply_text(f"پیش‌نویس شمارهٔ {draft_id} حذف شد.")
    else:
        await message.reply_text(f"پیش‌نویس شمارهٔ {draft_id} پیدا نشد.")


async def channels_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    clear_pending(context)
    message = update.effective_message
    if not message:
        return
    if not is_admin(update, context):
        await deny_access(update)
        return

    channels = db.list_channels()
    if not channels:
        await message.reply_text(
            "هنوز کانالی ثبت نشده است. از استودیو (/studio) کانال اضافه کن."
        )
        return
    lines = ["کانال‌های ثبت‌شده:"]
    for c in channels:
        flag = " ★ پیش‌فرض" if c["is_default"] else ""
        lines.append(f"• {c['title']} — {('@' + c['username']) if c['username'] else c['chat_id']}{flag}")
    await message.reply_text("\n".join(lines))


# ------------------------------------------------------------------ AI (Pollinations — free, no key)

POLL_TEXT_URL = "https://text.pollinations.ai/"
POLL_IMAGE_URL = "https://image.pollinations.ai/prompt/"
POLL_TEXT_MODEL = os.environ.get("POLL_TEXT_MODEL", "openai-fast").strip()
POLL_TIMEOUT_TEXT = 90
POLL_TIMEOUT_IMAGE = 180

AI_SYSTEM_PROMPT = (
    "تو دستیار هوش مصنوعی حرفه‌ای و دوستانه‌ی VoidFeedbot هستی. "
    "به زبان فارسی روان و واضح پاسخ بده. "
    "اگر کاربر به زبان دیگری نوشت، پاسخ را به زبانی که صحبت کرده بده ولی لحن دوستانه حفظ شود. "
    "پاسخ‌ها را برای نمایش در تلگرام کوتاه و خوانا بنویس؛ از پاراگراف‌های طولانی پرهیز کن."
)


async def ai_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """/ai <سوال> — چت با مدل رایگان Pollinations (openai-fast), بدون کلید."""
    clear_pending(context)
    message = update.effective_message
    if not message:
        return
    if not is_admin(update, context):
        await deny_access(update)
        return
    prompt = " ".join(context.args or []).strip()
    if not prompt:
        await message.reply_text(
            "یک سؤال بنویس. مثال:\n"
            "`/ai یک ایده‌ی جذاب برای پست سینمایی پیشنهاد بده`",
            parse_mode="Markdown",
        )
        return
    if len(prompt) > 4000:
        await message.reply_text("سؤال خیلی طولانی است (حداکثر ۴۰۰۰ نویسه).")
        return

    await context.bot.send_chat_action(message.chat_id, "typing")
    status = await message.reply_text("🤔 در حال فکر کردن…")
    payload = {
        "messages": [
            {"role": "system", "content": AI_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "model": POLL_TEXT_MODEL,
    }
    text = None
    last_err = ""
    async with httpx.AsyncClient(timeout=POLL_TIMEOUT_TEXT, trust_env=False) as client:
        for attempt in range(2):
            try:
                r = await client.post(POLL_TEXT_URL, json=payload)
                if r.status_code == 200 and (r.text or "").strip():
                    text = r.text.strip()
                    break
                last_err = f"HTTP {r.status_code}: {(r.text or '')[:200]}"
            except Exception as exc:
                last_err = f"{type(exc).__name__}: {str(exc)[:200]}"
            if attempt == 0:
                await asyncio.sleep(3)
    try:
        await status.delete()
    except Exception:
        pass

    if not text:
        await message.reply_text(
            f"❌ پاسخی از سرور هوش مصنوعی نگرفتم.\n{last_err}\n\nکمی بعد دوباره امتحان کن."
        )
        return

    # Telegram message limit = 4096; split on paragraph boundaries.
    while text:
        chunk = text[:4000]
        if len(text) > 4000:
            split_at = chunk.rfind("\n")
            if split_at > 500:
                chunk = chunk[:split_at]
        await message.reply_text(chunk)
        text = text[len(chunk):].lstrip("\n")


async def draw_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """/draw <پرامپت انگلیسی> — ساخت تصویر با Pollinations/Flux، بدون کلید."""
    clear_pending(context)
    message = update.effective_message
    if not message:
        return
    if not is_admin(update, context):
        await deny_access(update)
        return
    prompt = " ".join(context.args or []).strip()
    if not prompt:
        await message.reply_text(
            "موضوع تصویر را به انگلیسی بنویس. مثال:\n"
            "`/draw cyberpunk neon room 8k`",
            parse_mode="Markdown",
        )
        return
    if len(prompt) > 1000:
        await message.reply_text("پرامپت خیلی طولانی است (حداکثر ۱۰۰۰ نویسه).")
        return

    await context.bot.send_chat_action(message.chat_id, "upload_photo")
    status = await message.reply_text("🎨 در حال ساخت تصویر… (ممکن است تا یک دقیقه طول بکشد)")

    import urllib.parse as _up
    encoded = _up.quote(prompt, safe="")
    url = f"{POLL_IMAGE_URL}{encoded}?width=1024&height=1024&nologo=true"

    img_bytes = None
    last_err = ""
    async with httpx.AsyncClient(timeout=POLL_TIMEOUT_IMAGE, trust_env=False,
                                 follow_redirects=True) as client:
        for attempt in range(2):
            try:
                r = await client.get(url)
                ctype = (r.headers.get("content-type") or "").lower()
                if r.status_code == 200 and r.content and "image" in ctype:
                    img_bytes = r.content
                    break
                last_err = f"HTTP {r.status_code} ({ctype}): {(r.text or '')[:200]}"
            except Exception as exc:
                last_err = f"{type(exc).__name__}: {str(exc)[:200]}"
            if attempt == 0:
                await asyncio.sleep(4)

    try:
        await status.delete()
    except Exception:
        pass

    if not img_bytes:
        await message.reply_text(
            f"❌ ساخت تصویر ناموفق بود.\n{last_err}\n\nپرامپت دیگری امتحان کن."
        )
        return

    import io as _io
    bio = _io.BytesIO(img_bytes)
    bio.name = "voidfeed_ai.jpg"
    try:
        await message.reply_photo(
            photo=bio,
            caption=f"🎨 {prompt[:900]}",
        )
    except Exception as exc:
        await message.reply_text(f"خطا در ارسال تصویر به تلگرام: {exc}")


async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    error = context.error
    if error is None:
        logger.error("Telegram update failed without an exception object.")
        return
    logger.error(
        "Unhandled Telegram update error: %s",
        error,
        exc_info=(type(error), error, error.__traceback__),
    )


# ------------------------------------------------------------------ setup

async def post_init(app: Application) -> None:
    bot = app.bot
    try:
        await bot.set_my_commands([
            BotCommand("start", "منوی کامل بات"),
            BotCommand("menu", "باز کردن منوی اصلی"),
            BotCommand("lang", "زبان: en / fa / Language: en / fa"),
            BotCommand("studio", "استودیوی تولید محتوا"),
            BotCommand("draft", "ساخت پیش‌نویس"),
            BotCommand("queue", "فهرست پیش‌نویس‌ها"),
            BotCommand("approve", "تأیید پیش‌نویس"),
            BotCommand("reject", "رد پیش‌نویس"),
            BotCommand("publish", "انتشار فوری"),
            BotCommand("cancel", "لغو زمان‌بندی"),
            BotCommand("delete", "حذف پیش‌نویس"),
            BotCommand("channels", "کانال‌های ثبت‌شده"),
            BotCommand("news", "اخبار: on/off/now/sched/topic"),
            BotCommand("gen", "تولید پست با AI: now/on/off/cats"),
            BotCommand("ai", "چت با هوش مصنوعی"),
            BotCommand("draw", "ساخت تصویر با AI"),
            BotCommand("modstats", "آمار ناظر"),
            BotCommand("help", "راهنمای کامل"),
        ])
        await bot.set_my_commands(
            [
                BotCommand("warn", "اخطار (ریپلای)"),
                BotCommand("mute", "سکوت به دقیقه (ریپلای)"),
                BotCommand("ban", "بن دائمی (ریپلای)"),
                BotCommand("unban", "رفع بن"),
                BotCommand("kick", "اخراج (ریپلای)"),
                BotCommand("report", "گزارش کاربر (ریپلای)"),
                BotCommand("del", "حذف پیام (ریپلای)"),
                BotCommand("mod", "ناظر خودکار on/off"),
                BotCommand("modstats", "آمار ناظر"),
            ],
            scope=BotCommandScopeAllGroupChats(),
        )
    except Exception:
        logger.exception("set_my_commands failed")
    try:
        await bot.set_my_short_description(
            short_description=(
                "ربات خصوصی مدیریت کانال VoidFeed: اخبار خودکار، "
                "تولید پست با AI (فیلم/سریال/موسیقی/بازی)، "
                "پیش‌نویس و انتشار، استودیو.")
        )
        await bot.set_my_description(
            description=(
                "VoidFeedBot — ربات مدیریت کانال VoidFeed (دسترسی خصوصی).\n\n"
                "منوی اصلی: /menu یا /start\n"
                "📰 اخبار خودکار: /news (وضعیت، انتشار فوری، زمان‌بندی، موضوعات)\n"
                "🎬 تولید پست با AI: /gen (حالا، روشن/خاموش، انتخاب بخش)\n"
                "📝 پیش‌نویس‌ها: /draft /queue /approve /reject /publish /cancel /delete\n"
                "🌌 استودیو (وب‌اپ): /studio\n"
                "🤖 چت و تصویر با AI: /ai /draw\n"
                "❓ راهنمای کامل: /help")
        )
    except Exception:
        logger.exception("set_my_description failed")
    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="🌌 استودیو",
                web_app=WebAppInfo(url=STUDIO_URL),
            )
        )
        admin_id = app.bot_data.get("admin_id")
        if admin_id:
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text="🌌 استودیو",
                    web_app=WebAppInfo(url=STUDIO_URL),
                ),
                chat_id=admin_id,
            )
    except Exception:
        logger.exception("set_chat_menu_button failed")
    publisher_task = asyncio.get_running_loop().create_task(publisher_loop(app))
    app.bot_data["publisher_task"] = publisher_task
    try:
        import newsbot
        news_task = asyncio.get_running_loop().create_task(newsbot.news_loop(app))
        app.bot_data["news_task"] = news_task
    except Exception:
        logger.exception("news loop start failed")
    try:
        import contentgen
        gen_task = asyncio.get_running_loop().create_task(
            contentgen.contentgen_loop(app))
        app.bot_data["contentgen_task"] = gen_task
    except Exception:
        logger.exception("contentgen loop start failed")
    await startup_register(app)
    logger.info("Menu button and publisher initialized.")


async def post_stop(app: Application) -> None:
    for key in ("publisher_task", "news_task", "contentgen_task"):
        task = app.bot_data.get(key)
        if task:
            task.cancel()


def main() -> None:
    os.umask(0o077)
    load_dotenv(BASE_DIR / ".env")

    global STUDIO_URL
    STUDIO_URL = os.environ.get("STUDIO_URL", STUDIO_URL).strip()

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    raw_admin_id = os.environ.get("VOIDFEED_ADMIN_ID", "").strip()

    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set.")
    if not re.fullmatch(r"[1-9][0-9]{0,19}", raw_admin_id):
        raise SystemExit("VOIDFEED_ADMIN_ID is missing or invalid.")

    db.init_database()
    try:
        import moderator as _mod
        _mod.seed_words()
    except Exception:
        logger.exception("mod words seeding failed")

    from telegram.request import HTTPXRequest
    # media_write_timeout (default 20s) is for uploads — DPI can stall larger photos.
    # Also raise write_timeout so sendPhoto with caption doesn't time out through slow proxy.
    media_req = HTTPXRequest(
        connection_pool_size=16,
        read_timeout=30.0,
        write_timeout=120.0,
        connect_timeout=15.0,
        pool_timeout=5.0,
        media_write_timeout=120.0,
    )
    upd_req = HTTPXRequest(
        connection_pool_size=8,
        read_timeout=15.0,
        write_timeout=30.0,
        connect_timeout=15.0,
        pool_timeout=5.0,
    )
    app = (
        Application.builder()
        .token(token)
        .request(media_req)
        .get_updates_request(upd_req)
        .post_init(post_init)
        .post_stop(post_stop)
        .build()
    )
    app.bot_data["admin_id"] = int(raw_admin_id)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("lang", lang_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("studio", studio_command))
    app.add_handler(CommandHandler("draft", draft_command))
    app.add_handler(CommandHandler("queue", queue_command))
    app.add_handler(CommandHandler("approve", approve_command))
    app.add_handler(CommandHandler("reject", reject_command))
    app.add_handler(CommandHandler("publish", publish_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("delete", delete_command))
    app.add_handler(CommandHandler("channels", channels_command))
    app.add_handler(CommandHandler("syncchat", syncchat_command))
    app.add_handler(CommandHandler("warn", warn_command))
    app.add_handler(CommandHandler("mute", mute_command))
    app.add_handler(CommandHandler("ban", ban_command))
    app.add_handler(CommandHandler("unban", unban_command))
    app.add_handler(CommandHandler("kick", kick_command))
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(CommandHandler("del", delmsg_command))
    app.add_handler(CommandHandler("mod", mod_toggle_command))
    app.add_handler(CommandHandler("modstats", modstats_command))
    app.add_handler(CommandHandler("news", news_command))
    app.add_handler(CommandHandler("gen", gen_command))
    app.add_handler(CommandHandler("ai", ai_command))
    app.add_handler(CommandHandler("draw", draw_command))
    app.add_handler(CallbackQueryHandler(menu_callback))
    app.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS
            & (filters.TEXT | filters.CAPTION)
            & ~filters.COMMAND,
            moderate_group_message,
        )
    )
    app.add_handler(
        MessageHandler(
            filters.ChatType.CHANNEL & ~filters.COMMAND,
            channel_post_handler,
        )
    )
    app.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
            receive_draft,
        )
    )
    app.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & filters.PHOTO,
            receive_photo_forward,
        )
    )
    app.add_error_handler(error_handler)
    app.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
            topic_hashtags,
        ),
        group=1,
    )
    app.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
            submit_news,
        ),
        group=1,
    )

    logger.info("VoidFeedBot core v2 starting (studio=%s).", STUDIO_URL)
    app.run_polling(drop_pending_updates=False)


if __name__ == "__main__":
    main()
