"""VoidFeed newsbot — auto-publish news every N minutes with a real article image.

Cycle (default 30 min, run inside bot.py's event loop):
  1. Fetch RSS feeds of credible sources (through optional proxy, direct fallback).
  2. Pick the first unseen item (per-link dedupe in news_seen table).
  3. Resolve a real image: feed media/enclosure first, else og:image of the
     article; download to data/media/news/ (never post a fake/placeholder).
  4. Save a draft (source='news'), then publish it to the default channel
     if news_auto_publish is on.
Config lives in the settings table and is editable from the Studio.
"""
from __future__ import annotations

import asyncio
import hashlib
import html
import logging
import os
import re
from datetime import datetime
from pathlib import Path

import feedparser
import httpx

import voidfeed_db as db
import mediagen
from media_validate import validate_media

logger = logging.getLogger("VoidFeedNews")

try:
    from zoneinfo import ZoneInfo
    TEHRAN = ZoneInfo("Asia/Tehran")
except Exception:  # pragma: no cover
    TEHRAN = None


NEWS_DEFAULT_SOURCES = [
    # cinema / film
    {"name": "Variety", "url": "https://variety.com/feed/", "cat": "cinema"},
    {"name": "Deadline", "url": "https://deadline.com/feed/", "cat": "cinema"},
    # TV series
    {"name": "ScreenRant", "url": "https://screenrant.com/feed/", "cat": "series"},
    {"name": "TVLine", "url": "https://tvline.com/feed/", "cat": "series"},
    # games
    {"name": "IGN", "url": "https://feeds.feedburner.com/ign/all", "cat": "games"},
    {"name": "GameSpot", "url": "https://www.gamespot.com/feeds/news/", "cat": "games"},
    # celebrities
    {"name": "US Weekly", "url": "https://www.usmagazine.com/feed/", "cat": "celebs"},
    # music (film/TV scores & soundtracks included)
    {"name": "Rolling Stone", "url": "https://www.rollingstone.com/feed/", "cat": "music"},
    {"name": "Billboard", "url": "https://www.billboard.com/feed/", "cat": "music"},
    {"name": "NME", "url": "https://www.nme.com/feed", "cat": "music"},
    {"name": "Film Music Reporter", "url": "https://filmmusicreporter.com/feed/", "cat": "music"},
    # rumors (high-probability scoops across cinema/series/games)
    {"name": "ComicBook", "url": "https://comicbook.com/feed/", "cat": "rumor"},
    {"name": "Giant Freakin Robot", "url": "https://www.giantfreakinrobot.com/feed", "cat": "rumor"},
]

CAT_FA = {
    "games": "بازی", "cinema": "سینما", "series": "سریال",
    "music": "موسیقی", "celebs": "سلبریتی", "rumor": "شایعه", "news": "خبر",
}

TELEGRAM_API = "https://api.telegram.org"


def _sources() -> list[dict]:
    import json
    raw = db.get_setting("news_sources", "")
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list) and parsed:
                return parsed
        except Exception:
            pass
    return NEWS_DEFAULT_SOURCES


def _proxy() -> str | None:
    p = (db.get_setting("news_proxy", "")
         or os.environ.get("NEWS_PROXY", "")).strip()
    return p or None


def _clean_title(raw: str) -> str:
    t = html.unescape(re.sub(r"<[^>]+>", "", raw or "")).strip()
    return re.sub(r"\s+", " ", t)


def _link_hash(link: str) -> str:
    return hashlib.sha1((link or "").strip().encode()).hexdigest()


_UA = {"User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) VoidFeedBot/2.0 Chrome/124.0 Safari/537.36")}


async def _fetch_feed(url: str) -> bytes | None:
    """Fetch feed bytes; proxy client first (if set), then direct.

    Note: proxy/trust_env belong to the AsyncClient constructor in httpx,
    NOT to .get() — passing them per-request raises TypeError.
    """
    proxy = _proxy()
    attempts: list[dict] = ([{"proxy": proxy}] if proxy else []) + [{}]
    for attempt, kwargs in enumerate(attempts, 1):
        try:
            async with httpx.AsyncClient(follow_redirects=True,
                                         trust_env=False, **kwargs) as client:
                r = await client.get(url, headers=_UA, timeout=25)
            if r.status_code == 200 and r.content:
                return r.content
            logger.debug("feed try %s %s -> HTTP %s", attempt, url, r.status_code)
        except Exception as exc:
            logger.debug("feed fetch try %s failed for %s: %s", attempt, url, exc)
    return None


def _pick_items(feed_bytes: bytes, source: dict, max_items: int = 8) -> list[dict]:
    """All usable entries of a feed (newest first)."""
    try:
        parsed = feedparser.parse(feed_bytes)
    except Exception:
        return []
    out = []
    for entry in parsed.entries or []:
        title = _clean_title(getattr(entry, "title", ""))
        link = getattr(entry, "link", "") or ""
        if not title or not link:
            continue
        out.append({"title": title, "link": link,
                    "source": source["name"], "cat": source.get("cat", "news"),
                    "image": _item_image(entry), "video": _item_video(entry)})
        if len(out) >= max_items:
            break
    return out


def _item_image(entry) -> str:
    """Best image URL from an RSS entry (media:content/thumbnail/enclosure)."""
    for m in (getattr(entry, "media_content", []) or []):
        u = (m.get("url") or "").strip()
        if u and (m.get("medium") in ("image", None, "")
                  or "image" in (m.get("type") or "")):
            return u
    for m in (getattr(entry, "media_thumbnail", []) or []):
        u = (m.get("url") or "").strip()
        if u:
            return u
    for enc in (getattr(entry, "enclosures", []) or []):
        u = (enc.get("href") or "").strip()
        if u and ((enc.get("type") or "").startswith("image") or _img_url(u)):
            return u
    for l in (getattr(entry, "links", []) or []):
        u = (l.get("href") or "").strip()
        if l.get("rel") == "enclosure" and u and _img_url(u):
            return u
    return ""


def _img_url(u: str) -> bool:
    path = (u or "").split("?", 1)[0].lower()
    return path.endswith((".jpg", ".jpeg", ".png", ".webp", ".avif"))


def _vid_url(u: str) -> bool:
    path = (u or "").split("?", 1)[0].lower()
    return path.endswith((".mp4", ".m4v", ".mov", ".webm"))


# Video-page hosts whose og:video points to a PLAYER (YouTube/etc.), not a
# downloadable file. When a news item has no direct mp4, we still surface the
# article's embedded player link instead of dropping video entirely.
_EMBED_HOSTS = ("youtube.com", "youtu.be", "vimeo.com", "dailymotion.com",
                "twitch.tv", "facebook.com", "instagram.com")


def _is_embed_video(url: str) -> bool:
    u = (url or "").lower()
    return any(h in u for h in _EMBED_HOSTS)


def _append_embed(content: str, url: str | None) -> str:
    """Append an embedded-player (YouTube etc.) video link to a caption."""
    if url and _is_embed_video(url) and url not in content:
        return content.rstrip() + f"\n🎬 تماشای ویدیو: {url}"
    return content


def _item_video(entry) -> str:
    """Best direct video URL from an RSS entry (media:content/enclosure)."""
    for m in (getattr(entry, "media_content", []) or []):
        u = (m.get("url") or "").strip()
        if u and (m.get("medium") == "video" or "video" in (m.get("type") or "")):
            return u
    for enc in (getattr(entry, "enclosures", []) or []):
        u = (enc.get("href") or "").strip()
        if u and ((enc.get("type") or "").startswith("video") or _vid_url(u)):
            return u
    for l in (getattr(entry, "links", []) or []):
        u = (l.get("href") or "").strip()
        if l.get("rel") == "enclosure" and u and _vid_url(u):
            return u
    return ""


_OG_RE = re.compile(
    r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)["\']'
    r'|<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image(?::secure_url)?["\']',
    re.I)


async def _og_image(link: str) -> str:
    """Fetch the article page and pull og:image (feeds without enclosures)."""
    try:
        async with httpx.AsyncClient(follow_redirects=True,
                                     trust_env=False, headers=_UA) as client:
            r = await client.get(link, timeout=15)
        if r.status_code != 200:
            return ""
        m = _OG_RE.search(r.text[:200000])
        if not m:
            return ""
        return (m.group(1) or m.group(2) or "").strip()
    except Exception:
        return ""


_OG_VIDEO_RE = re.compile(
    r'<meta[^>]+property=["\']og:video(?::(?:secure_url|url))?["\'][^>]+content=["\']([^"\']+)["\']'
    r'|<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:video(?::(?:secure_url|url))?["\']'
    r'|<meta[^>]+name=["\']twitter:player:stream["\'][^>]+content=["\']([^"\']+)["\']'
    r'|<video[^>]*>\s*<source[^>]+(?:src|data-src)=["\']([^"\']+\.mp4)["\']'
    r'|<video[^>]+(?:src|data-src)=["\']([^"\']+\.mp4)["\']',
    re.I)


def _og_image_from(page: str) -> str:
    m = _OG_RE.search((page or "")[:200000])
    return (m.group(1) or m.group(2) or "").strip() if m else ""


def _og_video_from(page: str) -> str:
    m = _OG_VIDEO_RE.search((page or "")[:200000])
    if not m:
        return ""
    return (m.group(1) or m.group(2) or m.group(3)
            or m.group(4) or m.group(5) or "").strip()


async def _og_video(link: str) -> str:
    """Fetch the article page and pull og:video / twitter:player:stream."""
    try:
        async with httpx.AsyncClient(follow_redirects=True,
                                     trust_env=False, headers=_UA) as client:
            r = await client.get(link, timeout=15)
        if r.status_code != 200:
            return ""
        return _og_video_from(r.text)
    except Exception:
        return ""


async def _download_image(url: str, link_hash: str) -> str | None:
    """Download a real news image to data/media/news/; returns local path or None."""
    if not url or not _img_url(url):
        return None
    ext = url.split("?", 1)[0].lower().rsplit(".", 1)[-1]
    if ext not in ("jpg", "jpeg", "png", "webp", "avif"):
        ext = "jpg"
    dest = Path("data/media/news")
    try:
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / f"{link_hash[:16]}.{ext}"
        async with httpx.AsyncClient(follow_redirects=True,
                                     trust_env=False, headers=_UA) as client:
            r = await client.get(url, timeout=30)
        body = r.content or b""
        if r.status_code != 200 or len(body) < 3000:
            return None
        if not (body[:3] == b"\xff\xd8\xff" or body[:8] == b"\x89PNG\r\n\x1a\n"
                or body[:4] == b"RIFF" or body[:3] == b"GIF"):
            return None  # not a real image — skip rather than post a fake
        path.write_bytes(body)
        return str(path)
    except Exception as exc:
        logger.debug("image download failed for %s: %s", url[:80], exc)
        return None


async def _download_video(url: str, link_hash: str) -> str | None:
    """Download a real short news video (mp4) to data/media/news/; ≤45 MB."""
    if not url or not _vid_url(url):
        return None
    ext = url.split("?", 1)[0].lower().rsplit(".", 1)[-1]
    if ext not in ("mp4", "m4v"):
        return None  # sendVideo needs mp4 — skip other containers
    dest = Path("data/media/news")
    try:
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / f"{link_hash[:16]}.mp4"
        async with httpx.AsyncClient(follow_redirects=True,
                                     trust_env=False, headers=_UA) as client:
            r = await client.get(url, timeout=120)
        body = r.content or b""
        if (r.status_code != 200 or len(body) < 100000
                or len(body) > 45 * 1024 * 1024):
            return None
        if len(body) < 12 or body[4:8] != b"ftyp":
            return None  # not a real mp4 — skip rather than post a fake
        path.write_bytes(body)
        return str(path)
    except Exception as exc:
        logger.debug("video download failed for %s: %s", url[:80], exc)
        return None


def _topics() -> set[str]:
    """Selected topic categories from settings; empty set = all topics."""
    raw = (db.get_setting("news_topics", "") or "").strip()
    if not raw:
        return set()
    return {c for c in raw.split(",") if c}


def _has_persian(text: str) -> bool:
    return bool(re.search(r"[\u0600-\u06FF]", text or ""))


def _sched_slots() -> list[str]:
    """Manual publication hours (Tehran HH:MM) when scheduler mode is on."""
    if db.get_setting("news_sched_enabled", "0") != "1":
        return []
    raw = (db.get_setting("news_sched_hours", "") or "").replace("،", ",")
    out = set()
    for tok in raw.split(","):
        tok = tok.strip()
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", tok)
        if m and int(m.group(1)) <= 23 and int(m.group(2)) <= 59:
            out.add(f"{int(m.group(1)):02d}:{m.group(2)}")
    return sorted(out)


def _caption(item: dict, title_fa: str) -> str:
    """Hashtag-first branded caption: #موضوع at the very top."""
    cat_fa = CAT_FA.get(item["cat"], "خبر")
    return (
        f"#{cat_fa.replace(' ', '_')}\n\n"
        f"📰 {title_fa}\n\n"
        f"🔗 منبع: {item['source']}\n{item['link']}"
    )


_NEWS_TERMS = {}  # kept for reference only


def _stem_word(word: str) -> str:
    """Very simple English stemmer: remove common suffixes."""
    for suf, alt in [
        ("ies", "y"), ("ves", "fe"),
        ("es", ""), ("ed", ""), ("es", ""),
        ("ing", ""), ("s", ""),
    ]:
        if word.endswith(suf):
            return word[:-len(suf)] + alt
    return word


def _quick_fa(title_en: str) -> str | None:
    """Translate a gaming/tech/news English headline to a readable Persian approximation.

    Uses dictionary-based substitution — no external API needed, works offline.
    Returns None if the result would be identical to input (not English).
    """
    t = title_en
    # simple word-level replacements
    replacements = [
        (" confirmed ", " تأیید شد "),
        (" announced ", " اعلام شد "),
        (" revealed ", " رونمایی شد "),
        (" leaked ", " لو رفت "),
        (" released ", " منتشر شد "),
        (" released", " منتشر شد"),
        (" launches ", " عرضه می‌شود "),
        (" launch ", " عرضه "),
        (" is getting ", " در حال ساخت است "),
        (" might ", " ممکن است "),
        (" could ", " ممکن است "),
        (" millions ", " میلیون "),
        (" million ", " میلیون "),
        (" billions ", " میلیارد "),
        (" billion ", " میلیارد "),
        (" sale ", " فروش "),
        (" on sale ", " با تخفیف "),
        (" price ", " قیمت "),
        (" rumors ", " شایعه "),
        (" rumor ", " شایعه "),
        (" to be ", " که "),
        (" here's ", " این "),
        (" Here's ", " این "),
        (" this weekend ", " این آخر هفته "),
        (" weekend ", " آخر هفته "),
        (" by next year ", " تا سال آینده "),
        (" next year ", " سال آینده "),
        (" by 202", " تا 20"),
        (" US ", " آمریکا "),
        (" America ", " آمریکا "),
        (" season ", " فصل "),
        (" episode ", " قسمت "),
        (" streaming ", " استریم "),
        (" movie ", " فیلم "),
        (" film ", " فیلم "),
        (" video ", " ویدیو "),
        (" game ", " بازی "),
        (" coming ", " در راه "),
        (" upcoming ", " آینده "),
        (" new ", " جدید "),
        (" latest ", " آخرین "),
        (" first time ", " برای اولین بار "),
        (" first ", " اولین "),
        (" free to play ", " بازی رایگان "),
        (" free ", " رایگان "),
        (" announced at ", " اعلام شد در "),
        (" is coming to ", " می‌آید به "),
        (" is now available ", " الان قابل دسترس است "),
        (" is available ", " قابل دسترس است "),
        (" everything we know about ", " هر آنچه درباره "),
        (" everything about ", " همه چیز درباره "),
        (" here are ", " اینها هستند "),
        (" here's ", " این "),
        (" here's what ", " چی "),
        (" and more ", " و بیشتر "),
        (" and everything ", " و همه چیز "),
        (" might be ", " ممکن است باشد "),
        (" can now ", " الان می‌تواند "),
        (" can be ", " می‌تواند باشد "),
        (" to make ", " برای ساخت "),
        (" you can ", " می‌توانید "),
        (" we know ", " می‌دانیم "),
        (" we have ", " داریم "),
        (" for the first time ", " برای اولین بار "),
        (" gets a ", " یک "),
        (" gets ", " دریافت کرد "),
        (" has a ", " یک "),
        (" has been ", " شده است "),
        (" will be ", " خواهد بود "),
        (" should be ", " باید باشد "),
        (" in the U.S. ", " در آمریکا "),
        (" in US ", " در آمریکا "),
        (" in America ", " در آمریکا "),
        (" to the US ", " به آمریکا "),
        (" in the UK ", " در بریتانیا "),
        (" worldwide ", " در سراسر جهان "),
        (" global release ", " عرضه جهانی "),
        (" early access ", " دسترسی زودهنگام "),
        (" beta ", " بتا "),
        (" DLC ", " دی‌ال‌سی "),
        (" patch ", " آپدیت "),
        (" update ", " آپدیت "),
        (" update: ", " آپدیت: "),
        (" trailer ", " تریلر "),
        (" gameplay ", " گیم‌پلی "),
        (" screenshot ", " اسکرین‌شات "),
        (" image ", " تصویر "),
        (" official ", " رسمی "),
        (" reportedly ", " به گزارش "),
        (" source ", " منبع "),
        (" news ", " خبر "),
        (" report ", " گزارش "),
        (" exclusive ", " اختصاصی "),
    ]

    for en, fa in replacements:
        t = t.replace(en, fa)

    # check if English remained (not really translated)
    if t == title_en or title_en.lower() == t.lower():
        return None
    return t


async def _ai_translate(title_en: str) -> str | None:
    """Natural EN→FA via the configured provider (studio.ai_chat).

    Keeps proper nouns (movie/series/game titles, artist names, studios) in
    their original language; uses an established Persian title only when one
    really exists; never returns stiff machine-translation-style Persian.
    Does NOT drop to the free Pollinations endpoint: if every configured model
    fails (e.g. quota exhausted), returns None so the caller's MyMemory /
    dictionary fallbacks are used instead of machine-garbage.
    """
    messages = [
        {"role": "system", "content": (
            "تو مترجم حرفه‌ای انگلیسی به فارسی هستی. "
            "نام‌های خاص (عنوان فیلم/سریال، نام هنرمند، عنوان بازی، استودیو و…) را به زبان اصلی نگه دار. "
            "اگر برای عنوانی ترجمه رسمی و جاافتاده فارسی وجود دارد از همان استفاده کن؛ در غیر این صورت خود واژه اصلی را نگه دار. "
            "ترجمه روان، طبیعی و با دستور زبان درست فارسی باشد؛ نه ترجمه ماشینی خشک. "
            "فقط متن ترجمه‌شده را برگردان.")},
        {"role": "user", "content": f"این تیتر خبر را به فارسی طبیعی ترجمه کن:\n{title_en}"},
    ]
    try:
        import studio
        text = await asyncio.wait_for(studio.ai_chat(messages), timeout=45)
    except Exception as exc:
        logger.debug("ai_translate (cfg) failed: %s", exc)
        text = None
    t = (text or "").strip()
    if not t or not _has_persian(t):
        return None
    return t


async def _translate_fa(title_en: str) -> str | None:
    """Translate an English headline to Persian.
    AI first (natural Persian, proper nouns kept), then MyMemory (free, no
    key), then dictionary fallback. Returns None on all failures — caller
    keeps the English title.
    """
    # Try AI (natural translation, proper nouns preserved)
    ai = await _ai_translate(title_en)
    if ai:
        logger.info("ai_translate: %s -> %s", title_en[:30], ai[:30])
        return ai

    # Try MyMemory
    result = await _mymemory_translate(title_en)
    if result:
        logger.info("mymemory: %s -> %s", title_en[:30], result[:30])
        return result

    # Fallback: dictionary-based (works offline, no API needed)
    quick = _quick_fa(title_en)
    if quick:
        logger.info("quick_dict: %s -> %s", title_en[:30], quick[:30])
        return quick

    return None


async def _mymemory_translate(title_en: str) -> str | None:
    try:
        r = await httpx.AsyncClient(timeout=15, trust_env=False).get(
            "https://api.mymemory.translated.net/get",
            params={"q": title_en[:500], "langpair": "en|fa"},
        )
        if r.status_code == 200:
            txt = (r.json().get("responseData", {}).get("translatedText") or "").strip()
            if txt and txt != title_en and len(txt) < 300:
                return txt
    except Exception as exc:
        logger.debug("mymemory failed: %s", exc)
    return None


async def _libre_translate(title_en: str) -> str | None:
    """Free public LibreTranslate instances as fallback."""
    instances = [
        "https://translate.argosopentech.com/translate",
        "https://translate.terraprint.co/translate",
        "https://libretranslate.com/translate",
    ]
    for url in instances:
        try:
            r = await httpx.AsyncClient(timeout=15, trust_env=False).post(
                url,
                json={"q": title_en[:1000], "source": "en", "target": "fa", "format": "text"},
                headers={"Content-Type": "application/json"},
            )
            if r.status_code == 200:
                txt = (r.json().get("translatedText") or "").strip()
                if txt and txt != title_en and len(txt) < 300:
                    return txt
        except Exception as exc:
            logger.debug("libre [%s] failed: %s", url, exc)
    return None


async def run_once(bot=None) -> dict:
    """One news cycle. Returns {published, draft_id, title_fa, ...} or {error}."""
    sources = _sources()
    topics = _topics()
    if not sources:
        return {"error": "هیچ منبع خبری تنظیم نشده است"}

    picked = None
    title_fa = ""
    fetch_err = ""
    tried: set[str] = set()  # links whose translation failed this cycle
    max_tries = 12
    for source in sources:
        if topics and source.get("cat", "news") not in topics:
            continue
        try:
            feed = await _fetch_feed(source["url"])
        except Exception as exc:
            fetch_err = f"{source['name']}: {exc}"
            continue
        if not feed:
            fetch_err = f"{source['name']}: پاسخ خالی"
            continue
        for item in _pick_items(feed, source):
            if item["link"] in tried:
                continue  # translation already failed this cycle
            title_fa = await _translate_fa(item["title"]) or ""
            if not _has_persian(title_fa):
                # Persian headline is mandatory — retry next cycle
                tried.add(item["link"])
                if len(tried) >= max_tries:
                    break
                continue
            if not db.news_seen_add(_link_hash(item["link"]),
                                    item["source"], item["title"]):
                continue  # already published/seen before
            picked = item
            break
        if picked or len(tried) >= max_tries:
            break
    db.news_seen_prune()

    db.set_setting("news_last_fetch", db.utc_now())
    if not picked:
        if tried:
            err = "ترجمه فارسی برای مطالب جدید ممکن نشد؛ دور بعد دوباره تلاش می‌شود"
        else:
            err = fetch_err or "مطلب جدیدی در موضوعات انتخابی پیدا نشد"
        db.set_setting("news_last_error", err[:300])
        return {"error": err}

    db.set_setting("news_last_error", "")
    content = _caption(picked, title_fa)
    default = db.get_default_channel()
    vid = picked.get("video") or await _og_video(picked["link"])
    vid_path = await _download_video(vid, _link_hash(picked["link"])) if vid else None
    if vid and not vid_path:
        logger.info("news video skipped (not a usable short mp4): %s", vid[:80])
    img = picked.get("image") or await _og_image(picked["link"])
    img_path = await _download_image(img, _link_hash(picked["link"])) if img else None
    if img and not img_path:
        logger.info("news image skipped (not a usable real image): %s", img[:80])
    content = _append_embed(content, vid if (vid and not vid_path) else None)
    draft_id = db.save_draft(
        content,
        channel_id=default["id"] if default else None,
        media_path=vid_path or img_path,
        media_kind=("video" if vid_path else "photo") if (vid_path or img_path) else None,
        source="news", status="draft",
    )
    db.set_draft_status(draft_id, "approved")

    result = {"draft_id": draft_id, "title_en": picked["title"], "title_fa": title_fa,
              "source": picked["source"], "cat": picked["cat"],
              "image": img_path or "", "video": vid_path or "",
              "published": False}

    if db.get_setting("news_auto_publish", "1") != "1" or not default:
        return result

    ok, err = await _publish(bot, default, content, img_path, vid_path)
    _record_publish_result(db.get_draft(draft_id), ok, default["id"], err)
    if ok:
        result["published"] = True
    else:
        result["error"] = err
    return result


MAX_PUBLISH_ATTEMPTS = 3


def _record_publish_result(row, ok: bool, channel_id: int | None,
                           error: str | None = None) -> None:
    """Unified news publish outcome (mirrors studio/bot semantics)."""
    if not row:
        return
    row = dict(row)  # sqlite3.Row → dict
    did = row["id"]
    if ok:
        db.set_draft_status(did, "published")
        db.update_draft(did, published_at=db.utc_now(),
                        channel_id=channel_id, publish_error=None, attempts=0)
        db.add_publish_event(did, channel_id, "published", triggered_by="news")
        return
    attempts = row.get("attempts", 0) + 1
    db.update_draft(did, publish_error=(error or "")[:500], attempts=attempts)
    db.add_publish_event(did, channel_id, "failed",
                         details=(error or "")[:300], triggered_by="news")
    if attempts >= MAX_PUBLISH_ATTEMPTS:
        db.update_draft(did, status="publish_failed")


async def _publish(bot, channel, text: str, image: str | None,
                   video: str | None = None):
    """Publish via the running bot, or via a direct Bot API call."""
    # Pre-flight Telegram media validation on every configured path.
    media_err = validate_media(
        "video" if video else ("photo" if image else None),
        video or image)
    if media_err:
        return False, media_err

    caption = (text or "")[:1024]
    try:
        if bot is not None:
            if video and Path(video).is_file():
                with open(video, "rb") as fh:
                    await bot.send_video(chat_id=channel["chat_id"], video=fh,
                                         caption=caption or None,
                                         supports_streaming=True,
                                         write_timeout=180)
                return True, None
            if image and Path(image).is_file():
                with open(image, "rb") as fh:
                    await bot.send_photo(chat_id=channel["chat_id"],
                                         photo=fh, caption=caption or None)
            else:
                await bot.send_message(chat_id=channel["chat_id"],
                                       text=text[:4096] or "…")
            return True, None
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            return False, "TELEGRAM_BOT_TOKEN تنظیم نشده است"
        if video and Path(video).is_file():
            with open(video, "rb") as fh:
                r = httpx.post(
                    f"{TELEGRAM_API}/bot{token}/sendVideo",
                    data={"chat_id": channel["chat_id"],
                          "caption": caption or None,
                          "supports_streaming": "true"},
                    files={"video": fh}, timeout=180, trust_env=False,
                )
            data = r.json()
            if data.get("ok"):
                return True, None
            return False, data.get("description", "خطای نامشخص تلگرام")
        if image and Path(image).is_file():
            with open(image, "rb") as fh:
                r = httpx.post(
                    f"{TELEGRAM_API}/bot{token}/sendPhoto",
                    data={"chat_id": channel["chat_id"],
                          "caption": caption or None},
                    files={"photo": fh}, timeout=120, trust_env=False,
                )
        else:
            r = httpx.post(
                f"{TELEGRAM_API}/bot{token}/sendMessage",
                json={"chat_id": channel["chat_id"], "text": text[:4096]},
                timeout=30, trust_env=False,
            )
        data = r.json()
        if data.get("ok"):
            return True, None
        return False, data.get("description", "خطای نامشخص تلگرام")
    except Exception as exc:
        return False, str(exc)


async def run_manual(bot, url: str, cat: str | None = None) -> dict:
    """Johnny submits a news link in the bot: fetch, translate, publish."""
    url = (url or "").strip().rstrip(").،,؛!")
    if not url.startswith(("http://", "https://")):
        return {"error": "لینک معتبر نیست (باید با http/https شروع شود)"}
    default = db.get_default_channel()
    if not default:
        return {"error": "هیچ کانال پیش‌فرضی ثبت نشده است (/syncchat)"}
    title = ""
    img_url_str = ""
    vid_url_str = ""
    try:
        async with httpx.AsyncClient(follow_redirects=True,
                                     trust_env=False, headers=_UA) as client:
            r = await client.get(url, timeout=25)
        if r.status_code == 200 and r.content:
            page = r.text
            m = re.search(
                r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']'
                r'|<title[^>]*>([^<]+)</title>', page, re.I)
            title = _clean_title(
                (m.group(1) or m.group(2) or "") if m else "")
            img_url_str = _og_image_from(page)
            vid_url_str = _og_video_from(page)
    except Exception as exc:
        logger.debug("manual news fetch failed: %s", exc)
    if not title:
        title = _clean_title(url.split("//", 1)[-1].split("/", 1)[0])
    title_fa = await _translate_fa(title) or ""
    if not _has_persian(title_fa):
        title_fa = title  # manual submission — Johnny saw this post coming
    source = url.split("//", 1)[-1].split("/", 1)[0].removeprefix("www.")
    content = _caption({"cat": cat or "news", "link": url, "source": source},
                       title_fa)
    h = _link_hash(url)
    vid_path = await _download_video(vid_url_str, h) if vid_url_str else None
    img_path = await _download_image(img_url_str, h) if img_url_str else None
    content = _append_embed(content, vid_url_str if (vid_url_str and not vid_path) else None)
    media_path = vid_path or img_path
    media_kind = ("video" if vid_path else "photo") if media_path else None
    draft_id = db.save_draft(
        content, channel_id=default["id"], media_path=media_path,
        media_kind=media_kind, source="news", status="draft",
    )
    db.set_draft_status(draft_id, "approved")
    db.news_seen_add(h, source, title)
    if db.get_setting("news_manual_auto_publish", "1") == "1":
        ok, err = await _publish(bot, default, content, img_path, vid_path)
        _record_publish_result(db.get_draft(draft_id), ok, default["id"], err)
        if ok:
            return {"draft_id": draft_id, "title_fa": title_fa,
                    "published": True, "media_kind": media_kind or "text"}
        return {"error": err or "انتشار ناموفق بود", "draft_id": draft_id}
    return {"draft_id": draft_id, "title_fa": title_fa, "published": False,
            "media_kind": media_kind or "text"}


def _interval_min() -> int:
    try:
        return int(db.get_setting("news_interval_min", "30") or 30)
    except ValueError:
        return 30


async def _cycle(app) -> None:
    try:
        result = await run_once(bot=app.bot)
    except Exception:
        logger.exception("news run_once failed")
        return
    if result.get("error"):
        logger.warning("news cycle: %s", result["error"])
    elif result.get("published"):
        logger.info("news published: %s", result.get("title_fa", "")[:80])
    else:
        logger.info("news draft #%s saved (auto-publish off)",
                    result.get("draft_id"))


async def news_loop(app) -> None:
    """Interval mode (every N min) or manual slot mode (Tehran HH:MM list)."""
    logger.info("News loop started.")
    while True:
        try:
            if db.get_setting("news_enabled", "1") == "1":
                slots = _sched_slots()
                if slots:
                    now = datetime.now(TEHRAN) if TEHRAN else datetime.now()
                    cur = now.strftime("%H:%M")
                    today = now.strftime("%Y-%m-%d")
                    already = (db.get_setting("news_last_slot", "") == cur
                               and db.get_setting("news_last_slot_day", "") == today)
                    if cur in slots and not already:
                        db.set_setting("news_last_slot", cur)
                        db.set_setting("news_last_slot_day", today)
                        logger.info("scheduled slot %s fired", cur)
                        await _cycle(app)
                else:
                    await _cycle(app)
        except asyncio.CancelledError:
            logger.info("News loop stopped.")
            raise
        except Exception:
            logger.exception("news cycle failed")
        if _sched_slots():
            await asyncio.sleep(30)  # tight tick so a slot minute is never missed
        else:
            await asyncio.sleep(max(10, _interval_min() * 60))
