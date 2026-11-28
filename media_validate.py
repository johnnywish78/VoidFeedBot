"""Verified Telegram Bot API media constraints (share of all publish paths).

Constraints sourced from the Telegram Bot API reference (api.telegram.org):
- sendPhoto: photo ≤ 10 MB; width+height ≤ 10000; width/height ratio ≤ 20.
- sendVideo: video ≤ 50 MB; must be a valid video (we require MP4 + ftyp box).
Nothing here is invented; limits match the Bot API docs.
"""
from pathlib import Path

PHOTO_MAX_BYTES = 10 * 1024 * 1024        # Bot API: photo ≤ 10 MB
PHOTO_MAX_DIM_SUM = 10000                  # Bot API: width + height ≤ 10000
PHOTO_MAX_ASPECT = 20                      # Bot API: width/height ratio ≤ 20
VIDEO_MAX_BYTES = 50 * 1024 * 1024        # Bot API: video ≤ 50 MB
VIDEO_ALLOWED_EXT = {".mp4"}               # sendVideo: MP4 is the safe target

_IMG_MAGIC_OK = (
    (b"\xff\xd8\xff",),          # JPEG
    (b"\x89PNG\r\n\x1a\n",),     # PNG
    (b"RIFF",),                  # WebP (RIFF....WEBP)
)


def validate_photo(path: str) -> str | None:
    """Return a user-facing error string, or None if the photo is sendable."""
    p = Path(path)
    if not p.is_file():
        return "پرونده رسانه پیدا نشد"
    try:
        if p.stat().st_size > PHOTO_MAX_BYTES:
            return "عکس حداکثر ۱۰ مگابایت است (Telegram Bot API)"
    except OSError:
        return "پرونده رسانه پیدا نشد"
    try:
        from PIL import Image
        with Image.open(p) as im:
            w, h = im.size
    except Exception:
        return "فایل تصویر نامعتبر است"
    if w + h > PHOTO_MAX_DIM_SUM:
        return f"ابعاد عکس بیش از حد تلگرام است ({w}+{h} > 10000)"
    ar = max(w, h) / max(1, min(w, h))
    if ar > PHOTO_MAX_ASPECT:
        return "نسبت ابعاد عکس بیش از ۲۰ است (حد تلگرام)"
    return None


def validate_video(path: str) -> str | None:
    """Return a user-facing error string, or None if the video is sendable."""
    p = Path(path)
    if not p.is_file():
        return "پرونده رسانه پیدا نشد"
    if p.suffix.lower() not in VIDEO_ALLOWED_EXT:
        return "ویدیو باید MP4 باشد"
    try:
        if p.stat().st_size > VIDEO_MAX_BYTES:
            return "ویدیو حداکثر ۵۰ مگابایت است (Telegram Bot API)"
    except OSError:
        return "پرونده رسانه پیدا نشد"
    try:
        with open(p, "rb") as fh:
            head = fh.read(32)
    except OSError:
        return "پرونده رسانه پیدا نشد"
    if len(head) < 12 or head[4:8] != b"ftyp":
        return "فایل ویدیوی نامعتبر است"
    return None


def validate_media(kind: str | None, path: str | None) -> str | None:
    """Validate any media kind. Returns error or None (None = sendable)."""
    if not path or not kind:
        return None
    if kind == "video":
        return validate_video(path)
    if kind == "photo":
        return validate_photo(path)
    return None
