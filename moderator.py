"""VoidFeedBot chat moderation — profanity/political/sexual filter + discipline.

Wordlists live in the DB (mod_words) and are managed from the Studio.
Seeded on first run from data/mod_words.json. Terms starting with "re:" are
treated as regular expressions (for indirect references).
"""
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import voidfeed_db as db

BASE_DIR = Path(__file__).resolve().parent
WORDS_PATH = BASE_DIR / "data" / "mod_words.json"

CAT_LABELS = {
    "profanity_fa": "فحاشی (فارسی)",
    "profanity_en": "فحاشی (انگلیسی)",
    "sexual_fa": "محتوای جنسی (فارسی)",
    "sexual_en": "محتوای جنسی (انگلیسی)",
    "political_fa": "بحث سیاسی (فارسی)",
    "political_en": "بحث سیاسی (انگلیسی)",
    "insult_fa": "توهین (فارسی)",
    "insult_en": "توهین (انگلیسی)",
    "porn_fa": "پورنوگرافی (فارسی)",
    "porn_en": "پورنوگرافی (انگلیسی)",
    "body_fa": "اشاره به اعضای خصوصی (فارسی)",
    "body_en": "اشاره به اعضای خصوصی (انگلیسی)",
    "immoral_fa": "محتوای غیراخلاقی (فارسی)",
    "immoral_en": "محتوای غیراخلاقی (انگلیسی)",
}

# Escalation: warning N -> action
ESCALATION = {
    1: ("delete", None),
    2: ("delete", None),
    3: ("mute", 60),          # 1 hour
    4: ("mute", 24 * 60),     # 24 hours
    5: ("mute", 7 * 24 * 60), # 1 week
}
BAN_FOREVER_STRIKES = 6

ZERO_WIDTH = ("\u200c", "\u200f", "\u200e", "\u202a", "\u202b", "\u202c", "\ufeff")

_words_cache = {"data": None, "ts": 0.0}
_CACHE_TTL = 30


def normalize(text: str) -> str:
    """Normalize Persian/Arabic variants + strip zero-widths + collapse repeats."""
    if not text:
        return ""
    t = text.lower()
    for ch in ZERO_WIDTH:
        t = t.replace(ch, "")
    t = t.replace("\u0640", "")  # tatweel/stretch: کــیون -> کیون
    t = t.replace("ي", "ی").replace("ك", "ک").replace("ة", "ه").replace("ؤ", "و")
    t = t.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ء", "")
    t = t.replace("ٔ", "").replace("َ", "").replace("ِ", "").replace("ُ", "")
    t = t.replace("ٰ", "ا")
    # collapse repeated letters ("fuuuck" -> "fuck", "کییییر" -> "کیر")
    t = re.sub(r"(.)\1+", r"\1", t)
    # common leetspeak inside latin words
    t = t.replace("0", "o").replace("1", "i").replace("3", "e")
    t = t.replace("4", "a").replace("5", "s").replace("7", "t")
    t = t.replace("@", "a").replace("$", "s")
    return t


# Categories that trigger an automatic report to the owner's private chat.
REPORT_CATS = {"porn_fa", "porn_en", "sexual_fa", "sexual_en",
               "body_fa", "body_en"}


def seed_words() -> None:
    """Import data/mod_words.json into mod_words table (first run only)."""
    try:
        with open(WORDS_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        data = {}
    for category, terms in (data or {}).items():
        for term in terms or []:
            db.mod_word_add(category, term, is_regex=False)
    invalidate_cache()


def load_words() -> dict[str, list[tuple[str, bool]]]:
    """{category: [(term, is_regex), ...]} — DB-backed, 30s cache."""
    now = time.time()
    if _words_cache["data"] is not None and now - _words_cache["ts"] < _CACHE_TTL:
        return _words_cache["data"]
    out: dict[str, list[tuple[str, bool]]] = {k: [] for k in CAT_LABELS}
    try:
        for row in db.mod_words_all():
            out.setdefault(row["category"], []).append(
                (row["term"], bool(row["is_regex"]))
            )
    except Exception:
        pass
    _words_cache["data"] = out
    _words_cache["ts"] = now
    return out


def invalidate_cache() -> None:
    _words_cache["data"] = None


# Suffixes commonly glued to Persian profanity: کسشو، کیرت، کونی، جنده‌ها...
_FA_SUFFIX = r"(?:شو|ها|های|هایی|ش|ت|م|یت|ید|یم|ی)?"


def classify(text: str) -> list[str]:
    """Return matched categories for a message text."""
    if not text or len(text) > 8000:
        return []
    t = normalize(text)
    words = load_words()
    matched = []
    for cat, terms in words.items():
        for term, is_regex in terms:
            try:
                if is_regex or term.startswith("re:"):
                    pattern = term[3:] if term.startswith("re:") else term
                    if re.search(pattern, t):
                        matched.append(cat)
                        break
                    continue
                p_norm = normalize(term)
                if not p_norm:
                    continue
                if re.fullmatch(r"[a-z0-9 ]+", p_norm):
                    if re.search(
                        r"(?<![a-z0-9])" + re.escape(p_norm) + r"(?![a-z0-9])", t
                    ):
                        matched.append(cat)
                        break
                else:
                    pat = (r"(?<![\u0600-\u06FF])" + re.escape(p_norm) + _FA_SUFFIX
                           + r"(?![\u0600-\u06FF])")
                    if re.search(pat, t):
                        matched.append(cat)
                        break
            except re.error:
                continue
    return matched


def ban_until_iso(minutes: int) -> str:
    return (
        datetime.now(timezone.utc) + timedelta(minutes=minutes)
    ).isoformat(timespec="seconds")


def strike_action(warnings: int) -> tuple[str, int | None, bool]:
    """Map current warning count -> (action, mute_minutes, ban_forever)."""
    if warnings >= BAN_FOREVER_STRIKES:
        return "ban", None, True
    action, minutes = ESCALATION.get(warnings, ("delete", None))
    return action, minutes, False
