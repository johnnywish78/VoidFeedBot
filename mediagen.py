"""VoidFeed mediagen — branded image + video generation per platform.

Images: PIL, dark cinematic card, Persian text shaped via arabic_reshaper+bidi.
Videos: ffmpeg Ken Burns (zoompan) over the generated/uploaded image,
        H.264 yuv420p +faststart, silent — sized per platform.
Everything lands in db.MEDIA_DIR and is served by the studio as /media/<name>.
"""
from __future__ import annotations

import os
import secrets
import subprocess
import time
from pathlib import Path

import voidfeed_db as db

# ---------------------------------------------------------------- platform specs

# (width, height, label)
PLATFORM_SIZES = {
    "telegram":        (1280, 720,  "Telegram 16:9"),
    "x":               (1200, 675,  "X 16:9"),
    "instagram_post":  (1080, 1350, "Instagram 4:5"),
    "instagram_story": (1080, 1920, "Instagram/Stories 9:16"),
    "facebook":        (1200, 630,  "Facebook 1.91:1"),
    "tiktok":          (1080, 1920, "TikTok 9:16"),
    "youtube_thumb":   (1280, 720,  "YouTube thumbnail"),
    "youtube_shorts":  (1080, 1920, "YouTube Shorts 9:16"),
}

BADGE_COLORS = {
    "cinema": (48, 130, 255), "series": (255, 122, 40),
    "games": (0, 170, 255), "music": (155, 81, 255),
    "tech": (0, 200, 160), "news": (230, 60, 90),
}

_FONTS = {
    "bold":  "/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf",
    "semi":  "/usr/share/fonts/truetype/noto/NotoSansArabic-SemiBold.ttf",
    "reg":   "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
    "latin": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
}


def _font(kind: str, size: int):
    from PIL import ImageFont
    path = _FONTS.get(kind, _FONTS["semi"])
    if not Path(path).is_file():
        path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    return ImageFont.truetype(path, size)


def _shape(text: str) -> str:
    """Shape Persian/Arabic text for PIL (no shaping built in)."""
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(text))
    except Exception:
        return text


def _is_latin(text: str) -> bool:
    latin = sum(1 for c in text if c.isascii() and c.isalpha())
    return latin > max(3, len([c for c in text if c.isalpha()]) // 2)


def _strip_emoji(text: str) -> str:
    out = []
    for ch in text:
        cp = ord(ch)
        if (0x1F000 <= cp <= 0x1FAFF) or (0x2600 <= cp <= 0x27BF) or cp in (0xFE0F, 0x200D):
            continue
        out.append(ch)
    return "".join(out).replace("  ", " ").strip()


def _wrap(draw, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _gradient(w: int, h: int, theme: str):
    """Vertical dark gradient with a subtle accent glow."""
    from PIL import Image, ImageDraw, ImageFilter
    accent = BADGE_COLORS.get(theme, (48, 130, 255))
    top = (10, 15, 26)
    bottom = (16 + accent[0] // 12, 20 + accent[1] // 14, 30 + accent[2] // 12)
    img = Image.new("RGB", (1, h))
    px = img.load()
    for y in range(h):
        t = y / max(1, h - 1)
        px[0, y] = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
    bg = img.resize((w, h))
    glow = Image.new("RGB", (w, h), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    cx, cy, r = int(w * 0.82), int(h * 0.16), int(min(w, h) * 0.55)
    gd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=tuple(int(c * 0.22) for c in accent))
    glow = glow.filter(ImageFilter.GaussianBlur(min(w, h) // 8))
    from PIL import ImageChops
    return ImageChops.add(bg, glow)


def generate_image(text: str, platform: str = "telegram",
                   theme: str = "news", source: str = "") -> str:
    """Render a branded card; returns the absolute path."""
    if platform not in PLATFORM_SIZES:
        raise ValueError(f"unknown platform: {platform}")
    w, h, _ = PLATFORM_SIZES[platform]
    from PIL import Image, ImageDraw

    clean = _strip_emoji((text or "").strip()) or "VoidFeed"
    shaped = _shape(clean) if not _is_latin(clean) else clean

    img = _gradient(w, h, theme)
    draw = ImageDraw.Draw(img)

    pad = int(w * 0.07)
    max_w = w - pad * 2

    # headline: auto font size to fit 1..4 lines
    n = max(1, min(4, (len(clean) // (22 if h > w else 16)) + 1))
    size = int(min(h * (0.085 if h > w else 0.11), w * 0.085))
    while size > 24:
        font = _font("bold", size)
        lines = _wrap(draw, shaped, font, max_w)
        if len(lines) <= n:
            break
        size = int(size * 0.92)
    lines = _wrap(draw, shaped, font, max_w)
    if len(lines) > 5:
        lines = lines[:5] + [lines[4][:30] + "…"]
        lines = lines[:5]

    # badge
    badge_txt = theme.upper() if _is_latin(theme) else _shape({
        "cinema": "سینما", "series": "سریال", "games": "بازی",
        "music": "موسیقی", "tech": "تکنولوژی", "news": "خبر",
    }.get(theme, "خبر"))
    bfont = _font("semi", int(w * 0.028) + 8)
    bw = draw.textlength(badge_txt, font=bfont)
    bh = int(w * 0.042) + 8
    color = BADGE_COLORS.get(theme, (48, 130, 255))
    by = int(h * 0.09)
    draw.rounded_rectangle([pad, by, pad + bw + 36, by + bh], radius=bh // 2, fill=color)
    draw.text((pad + 18, by + bh // 2), badge_txt, font=bfont, fill=(12, 16, 24), anchor="lm")

    # headline block
    line_h = int(size * 1.45)
    block_h = line_h * len(lines)
    text_top = h * 0.52 - block_h / 2 if h > w else h * 0.46 - block_h / 2
    y = int(text_top)
    for ln in lines:
        draw.text((pad, y), ln, font=font, fill=(238, 244, 250), anchor="la")
        y += line_h

    # source + brand footer
    ffont = _font("reg", int(w * 0.024) + 6)
    src = _shape(source.strip()) if source and not _is_latin(source) else (source or "").strip()
    if src:
        draw.text((pad, h - int(h * 0.065)), src[:60], font=ffont, fill=(150, 165, 185), anchor="ls")
    brand = "@FeedTheVoids" if _is_latin("@FeedTheVoids") else "@FeedTheVoids"
    draw.text((w - pad, h - int(h * 0.065)), brand, font=ffont, fill=color, anchor="rs")

    db.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    name = f"gen_{int(time.time())}_{secrets.token_hex(4)}.jpg"
    path = db.MEDIA_DIR / name
    img.save(path, "JPEG", quality=92)
    os.chmod(path, 0o600)
    return str(path)


def generate_video(image_path: str, platform: str = "tiktok",
                   seconds: int = 8) -> str:
    """Ken Burns motion over `image_path`, sized for platform; returns mp4 path."""
    if platform not in PLATFORM_SIZES:
        raise ValueError(f"unknown platform: {platform}")
    w, h, _ = PLATFORM_SIZES[platform]
    src = Path(image_path)
    if not src.is_file():
        raise FileNotFoundError(image_path)
    seconds = max(3, min(30, int(seconds)))
    fps = 24
    frames = seconds * fps

    db.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    out = db.MEDIA_DIR / f"gen_{int(time.time())}_{secrets.token_hex(4)}.mp4"
    fade_out = max(0.0, seconds - 0.6)
    vf = (
        f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,"
        f"crop={w * 2}:{h * 2},"
        f"zoompan=z='min(1+0.09*on/{frames},1.09)'"
        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1"
        f":s={w}x{h}:fps={fps},"
        f"fade=t=in:st=0:d=0.5,fade=t=out:st={fade_out}:d=0.6,"
        "format=yuv420p"
    )
    cmd = [
        "ffmpeg", "-y", "-loop", "1", "-i", str(src),
        "-vf", vf, "-t", str(seconds),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-movflags", "+faststart", "-an", str(out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if proc.returncode != 0 or not out.is_file() or out.stat().st_size < 1024:
        tail = (proc.stderr or "")[-400:]
        raise RuntimeError(f"ffmpeg failed: {tail}")
    os.chmod(out, 0o600)
    return str(out)
