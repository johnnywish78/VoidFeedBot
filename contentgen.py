"""VoidFeed contentgen — AI post generation sections (cinema/series/music/games).

Auto + manual generation of Persian intro posts (newest/best movies, series,
soundtracks, musicians & singers, PC/console/mobile games), with a branded
mediagen cover image, published straight to the default channel. Origin is
admin/AI, so it publishes without review (never enters the inappropriate-
content filter/report path).

Settings (settings table):
  gen_enabled       "1"/"0"  auto loop on/off
  gen_interval_min  minutes between auto posts (default 60)
  gen_sections      comma list of enabled section ids (empty = all)
  gen_cursor        rotation position across flattened (section, subtopic)
  gen_last_title / gen_last_at / gen_last_error
"""
from __future__ import annotations

import asyncio
import logging
import os
import re

import httpx
from fastapi import HTTPException

import voidfeed_db as db
import mediagen

logger = logging.getLogger("VoidFeedContentGen")

# Free Pollinations text fallback (same endpoint /ai command uses) — used only
# when every configured OpenAI-compatible model fails (e.g. quota exhausted).
POLL_TEXT_URL = "https://text.pollinations.ai/"
POLL_TEXT_MODEL = os.environ.get("POLL_TEXT_MODEL", "openai-fast").strip()
POLL_TIMEOUT_TEXT = 90

SECTIONS = {
    "cinema": {"fa": "سینما", "tag": "سینما", "theme": "cinema"},
    "series": {"fa": "سریال", "tag": "سریال", "theme": "series"},
    "music": {"fa": "موسیقی", "tag": "موسیقی", "theme": "music"},
    "games": {"fa": "بازی", "tag": "بازی", "theme": "games"},
}

GEN_CAT_MAP = {
    "سینما": "cinema", "فیلم": "cinema",
    "سریال": "series",
    "موسیقی": "music", "موزیک": "music",
    "بازی": "games", "گیم": "games",
}

SUBS = {
    "cinema": [
        ("movies_newest", "جدیدترین فیلم‌های سینمایی"),
        ("movies_best", "بهترین فیلم‌های سینمایی"),
    ],
    "series": [
        ("series_newest", "جدیدترین سریال‌ها"),
        ("series_best", "بهترین سریال‌ها"),
    ],
    "music": [
        ("soundtrack_newest", "جدیدترین موسیقی متن فیلم و سریال"),
        ("soundtrack_best", "بهترین موسیقی متن فیلم و سریال"),
        ("artists_newest", "جدیدترین موزیسین‌ها و خوانندگان"),
        ("artists_best", "بهترین موزیسین‌ها و خوانندگان"),
    ],
    "games": [
        ("pc_newest", "جدیدترین بازی‌های کامپیوتری (PC)"),
        ("pc_best", "بهترین بازی‌های کامپیوتری (PC)"),
        ("console_newest", "جدیدترین بازی‌های کنسولی"),
        ("console_best", "بهترین بازی‌های کنسولی"),
        ("mobile_newest", "جدیدترین بازی‌های تلفن همراه"),
        ("mobile_best", "بهترین بازی‌های تلفن همراه"),
    ],
}

DEFAULT_SECTIONS = ["cinema", "series", "music", "games"]

SYSTEM_PROMPT = (
    "تو دستیار تولید محتوای کانال تلگرامی VoidFeed هستی. "
    "پست‌های کوتاه، جذاب و حرفه‌ای به فارسی طبیعی می‌نویسی؛ لحن انسانی و گرم، نه رباتی. "
    "دستور زبان فارسی را دقیق رعایت کن و از ساختارهای ماشینی و ترجمه‌ی خشک پرهیز کن. "
    "نام‌های خاص (عنوان فیلم/سریال، نام هنرمند و خواننده، عنوان بازی، استودیو و…) را به زبان اصلی نگه دار؛ "
    "اگر برای عنوانی ترجمه رسمی و جاافتاده فارسی وجود دارد از همان استفاده کن، در غیر این صورت خود واژه اصلی را بیاور. "
    "اگر واژه‌ای معادل فارسی خوب ندارد، همان واژه اصلی را نگه دار. "
    "ساختار خروجی باید دقیقاً منظم باشد: هر مورد در یک خط جدا، با شماره (۱️⃣ ۲️⃣ …) شروع شود؛ "
    "نه متن پیوسته و نه آیتم‌های بهم‌ریخته. متن روان و بدون تکرار باشد. "
    "از مارک‌داون، ستاره، خط‌های بلند و ایموجی‌های اضافی پرهیز کن. "
    "طول پست همراه تصویر نباید از حدود ۹۵۰ نویسه بیشتر شود. "
    "فقط متن پست را برگردان، بدون توضیح اضافه، بدون گیومه، بدون امضا."
)


def _enabled_sections() -> list[str]:
    raw = (db.get_setting("gen_sections", "") or "").strip()
    if raw:
        out = [s for s in raw.split(",") if s in SECTIONS]
        if out:
            return out
    return list(DEFAULT_SECTIONS)


def _all_topics() -> list[dict]:
    out = []
    for cat in _enabled_sections():
        for sub_id, sub_fa in SUBS.get(cat, []):
            out.append({
                "cat": cat, "sub": sub_id, "fa": sub_fa,
                "section_fa": SECTIONS[cat]["fa"],
                "tag": SECTIONS[cat]["tag"],
                "theme": SECTIONS[cat]["theme"],
            })
    return out


def _cursor() -> int:
    try:
        return int(db.get_setting("gen_cursor", "0") or 0)
    except (TypeError, ValueError):
        return 0


def _set_cursor(idx: int) -> None:
    n = max(1, len(_all_topics()))
    db.set_setting("gen_cursor", str(idx % n))


def _has_persian(text: str) -> bool:
    return bool(re.search(r"[\u0600-\u06FF]", text or ""))


def _clean_text(text: str) -> str:
    """Strip markdown artifacts and collapse blank runs (plain Telegram caption)."""
    text = (text or "").replace("**", "").replace("__", "")
    out, blank = [], False
    for ln in text.splitlines():
        ln = ln.rstrip()
        if not ln.strip():
            if blank:
                continue
            blank = True
        else:
            blank = False
        out.append(ln)
    return "\n".join(out).strip()


def _normalize_post(text: str) -> str:
    """Normalize generated post layout: strip markdown, fix punctuation spacing,
    and put every numbered item on its own line."""
    t = _clean_text(text)
    t = re.sub(r"\s+([،؛؟!.:])", r"\1", t)
    t = re.sub(r"([،؛؟!.:])(?=\S)", r"\1 ", t)
    t = re.sub(r"(?<![\n\d])(\d{1,2}(?:[.)]|️⃣)\s*)", r"\n\1", t)
    out = []
    for ln in t.splitlines():
        ln = ln.strip()
        if ln:
            out.append(ln)
    return "\n".join(out).strip()


def _fit_caption(text: str, limit: int = 1000) -> str:
    """Truncate at the last sentence boundary within `limit` (Telegram 1024)."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    idx = max(cut.rfind("\n"), cut.rfind("."), cut.rfind("!"),
              cut.rfind("؟"), cut.rfind("…"))
    if idx > limit * 0.5:
        return cut[:idx + 1].rstrip()
    return cut.rstrip() + "…"


def _build_prompt(topic: dict) -> str:
    return (
        f"یک پست تلگرامی آمادهٔ انتشار برای کانال VoidFeed بنویس که «{topic['fa']}» را معرفی کند.\n"
        "ویژگی‌ها:\n"
        "- بین ۴ تا ۷ مورد واقعی و شاخص معرفی کن؛ هر مورد با یک خط توضیح جذاب و موجز.\n"
        "- لحن انسانی و طبیعی داشته باش؛ نه رباتی و نه ترجمه ماشینی.\n"
        "- عناوین و نام‌های خاص را به زبان اصلی نگه دار؛ فقط اگر ترجمه رسمی و جاافتادهٔ فارسی وجود داشت از آن استفاده کن.\n"
        "- اگر واژه‌ای معادل فارسی خوب ندارد، همان واژه اصلی را بیاور.\n"
        "- ساختار: هر مورد در یک خط جدا با شماره (۱️⃣ ۲️⃣ ۳️⃣ …) شروع شود؛ متن پیوسته و بهم‌ریخته نباشد.\n"
        "- از مارک‌داون و ستاره استفاده نکن.\n"
        "- از ایموجی‌های مناسب استفاده کن.\n"
        f"- در پایان هشتگ‌های مرتبط بگذار (شامل #{topic['tag']}).\n"
        "- طول کل همراه تصویر زیر ۹۵۰ نویسه بماند (کپشن تلگرام حداکثر ۱۰۲۴).\n"
        "- فقط متن پست را برگردان."
    )


async def _pollinations_generate(messages: list[dict]):
    """Free fallback generator; returns (text, None) or (None, error)."""
    payload = {"messages": messages, "model": POLL_TEXT_MODEL}
    last_err = None
    async with httpx.AsyncClient(timeout=POLL_TIMEOUT_TEXT,
                                 trust_env=False) as client:
        for attempt in range(2):
            try:
                r = await client.post(POLL_TEXT_URL, json=payload)
                if r.status_code == 200 and (r.text or "").strip():
                    return r.text.strip(), None
                last_err = f"HTTP {r.status_code}: {(r.text or '')[:200]}"
            except Exception as exc:
                last_err = f"{type(exc).__name__}: {str(exc)[:200]}"
            if attempt == 0:
                await asyncio.sleep(3)
    return None, last_err or "Pollinations ناموفق بود"


async def _ai_generate(topic: dict):
    """Return (text, None) or (None, error_str).

    Primary: studio.ai_chat (the configured provider trio). This NEVER falls
    back to the free Pollinations endpoint for publication: when every
    configured model fails (e.g. provider quota exhausted), the cycle reports an
    error instead of publishing low-quality/garbage text.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _build_prompt(topic)},
    ]
    text = None
    try:
        import studio
        text = await studio.ai_chat(messages)
    except Exception as exc:
        logger.warning("contentgen cfg AI failed: %s", exc)
    text = (text or "").strip()
    if text and _has_persian(text):
        return text, None
    return None, ("تولید با مدل‌های پیکربندی‌شده ناموفق بود "
                  "(پرووایدر در دسترس نیست یا توکن تمام شده)")


def _cover_image(text: str, topic: dict) -> str | None:
    """Branded mediagen card from the post's first line (headline)."""
    try:
        headline = text.splitlines()[0].strip()[:160] if text else topic["fa"]
        return mediagen.generate_image(headline, platform="telegram",
                                      theme=topic["theme"], source="")
    except Exception as exc:
        logger.warning("contentgen cover image failed: %s", exc)
        return None


async def _publish(bot, channel, text: str, image: str | None):
    import newsbot
    return await newsbot._publish(bot, channel, text, image)


async def run_once(bot, section=None, kind=None) -> dict:
    """Generate + publish one content post (manual or auto cycle)."""
    default = db.get_default_channel()
    if not default:
        return {"error": "هیچ کانال پیش‌فرضی ثبت نشده است (/syncchat)"}

    topics = _all_topics()
    if section and section in SECTIONS:
        topics = [t for t in topics if t["cat"] == section]
    if kind in ("newest", "best"):
        matched = [t for t in topics if kind in t["sub"]]
        if matched:
            topics = matched
    if not topics:
        return {"error": "هیچ موضوع فعالی برای تولید پیدا نشد"}

    idx = _cursor() % len(topics)
    topic = topics[idx]
    _set_cursor(idx + 1)

    db.set_setting("gen_last_error", "")
    text, err = await _ai_generate(topic)
    if err or not text:
        db.set_setting("gen_last_error", (err or "خطای نامشخص")[:300])
        return {"error": err or "تولید ناموفق بود"}
    text = _fit_caption(_normalize_post(text))

    img_path = _cover_image(text, topic)
    draft_id = db.save_draft(
        text, channel_id=default["id"], media_path=img_path,
        media_kind="photo" if img_path else None,
        source="contentgen", status="draft",
    )
    db.set_draft_status(draft_id, "approved")

    result = {
        "draft_id": draft_id, "cat": topic["cat"], "sub": topic["sub"],
        "title": text.splitlines()[0][:200] if text else "",
        "published": False,
    }

    ok, pub_err = await _publish(bot, default, text, img_path)
    if ok:
        db.set_draft_status(draft_id, "published")
        db.update_draft(draft_id, published_at=db.utc_now())
        db.set_setting("gen_last_title", result["title"])
        db.set_setting("gen_last_at", db.utc_now())
        result["published"] = True
    else:
        db.set_draft_status(draft_id, "publish_failed")
        db.update_draft(draft_id, publish_error=(pub_err or "")[:500])
        db.set_setting("gen_last_error", (pub_err or "")[:300])
        result["error"] = pub_err or "انتشار ناموفق بود"
    return result


def _interval_min() -> int:
    try:
        return max(10, int(db.get_setting("gen_interval_min", "60") or 60))
    except (TypeError, ValueError):
        return 60


async def _cycle(app) -> None:
    try:
        result = await run_once(bot=app.bot)
    except Exception:
        logger.exception("contentgen run_once failed")
        return
    if result.get("error"):
        logger.warning("contentgen cycle: %s", result["error"])
    elif result.get("published"):
        logger.info("contentgen published: %s", result.get("title", "")[:80])
    else:
        logger.info("contentgen draft #%s saved", result.get("draft_id"))


async def contentgen_loop(app) -> None:
    logger.info("Content-gen loop started.")
    while True:
        try:
            if db.get_setting("gen_enabled", "1") == "1":
                await _cycle(app)
        except asyncio.CancelledError:
            logger.info("Content-gen loop stopped.")
            raise
        except Exception:
            logger.exception("contentgen cycle failed")
        await asyncio.sleep(_interval_min() * 60)
