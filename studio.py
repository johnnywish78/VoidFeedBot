"""VoidFeed Studio — FastAPI backend + Mini App server.

Runs alongside bot.py (separate process, shared SQLite via voidfeed_db).
Auth: Telegram Mini App initData (Authorization: tma <initData>).
Demo mode for local testing: VOIDFEED_DEMO=1 env bypasses Telegram auth.
"""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
import urllib.parse
from pathlib import Path

import httpx
from fastapi import Body, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import voidfeed_db as db
from media_validate import validate_media

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s", level=logging.INFO
)
logger = logging.getLogger("VoidFeedStudio")

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "studio_web"

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")

# Ensure schema exists even when started as `uvicorn studio:app` (README's
# documented mode), which skips main(). Idempotent: mkdir exist_ok + IF NOT EXISTS.
db.init_database()

MAX_TEXT = 10000
ALLOWED_PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_VIDEO_EXT = {".mp4", ".mov", ".webm"}
MAX_PHOTO_BYTES = 20 * 1024 * 1024
MAX_VIDEO_BYTES = 50 * 1024 * 1024  # Bot API sendVideo limit

TELEGRAM_API = "https://api.telegram.org"

def _ai_cfg():
    return (
        os.environ.get("AI_API_BASE", "").strip(),
        os.environ.get("AI_API_KEY", "").strip(),
        os.environ.get("AI_MODEL", "").strip(),
        [m.strip() for m in os.environ.get(
            "AI_FALLBACK_MODELS",
            "zai-org/GLM-5.3-Flash,MiniMaxAI/MiniMax-M2.7",
        ).split(",") if m.strip()],
    )

DEMO = os.environ.get("VOIDFEED_DEMO", "").strip() == "1"

# Demo-mode safety: VOIDFEED_DEMO bypasses all auth, so it must never be able
# to run in a production-like configuration. Fail closed (refuse to boot)
# when the process looks like a production deployment: a production port or
# no explicit isolated WORK_DIR. Legitimate isolated demos keep working.
if DEMO:
    _demo_port = os.environ.get("STUDIO_PORT", "").strip()
    if _demo_port in ("8077", "8078"):
        raise RuntimeError(
            "VOIDFEED_DEMO refused: production port STUDIO_PORT=" + _demo_port)
    if not os.environ.get("WORK_DIR", "").strip():
        raise RuntimeError("VOIDFEED_DEMO refused: requires an isolated WORK_DIR")


def _bot_token() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


def _admin_id() -> int:
    try:
        return int(os.environ.get("VOIDFEED_ADMIN_ID", "0") or 0)
    except ValueError:
        return 0

app = FastAPI(title="VoidFeed Studio", docs_url=None, redoc_url=None)


# ------------------------------------------------------------------ auth

def validate_init_data(raw: str) -> dict:
    """Validate Telegram Mini App initData; returns the user dict."""
    bot_token = _bot_token()
    if not raw:
        raise HTTPException(401, "initData missing")
    pairs = {}
    for part in raw.split("&"):
        if "=" in part:
            k, v = part.split("=", 1)
            pairs[k] = urllib.parse.unquote(v)
    provided_hash = pairs.pop("hash", None)
    if not provided_hash:
        raise HTTPException(401, "initData hash missing")
    check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed, provided_hash):
        raise HTTPException(401, "initData signature invalid")

    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError:
        raise HTTPException(401, "initData auth_date invalid")
    if time.time() - auth_date > 86400:
        raise HTTPException(401, "initData expired")

    try:
        user = json.loads(pairs.get("user", "{}"))
    except json.JSONDecodeError:
        raise HTTPException(401, "initData user invalid")
    admin_id = _admin_id()
    if not admin_id or user.get("id") != admin_id:
        raise HTTPException(403, "دسترسی فقط برای مدیر مجاز است.")
    return user


def require_admin(authorization: str | None) -> dict:
    if DEMO:
        return {"id": _admin_id() or 220297612, "first_name": "Demo"}
    # Optional standalone access: Authorization: Bearer <STUDIO_ADMIN_TOKEN>.
    # Enabled ONLY when the env var is set; constant-time compare; never logged.
    admin_token = os.environ.get("STUDIO_ADMIN_TOKEN", "").strip()
    raw = authorization or ""
    if admin_token and raw.startswith("Bearer "):
        supplied = raw[7:].strip()
        if supplied and hmac.compare_digest(supplied, admin_token):
            return {"id": _admin_id() or 0, "first_name": "Admin",
                    "auth": "token"}
        raise HTTPException(401, "Invalid studio token")
    if not _bot_token():
        raise HTTPException(503, "TELEGRAM_BOT_TOKEN is not set.")
    if not raw.startswith("tma "):
        raise HTTPException(401, "Authorization header must be 'tma <initData>'")
    return validate_init_data(raw[4:].strip())


# ------------------------------------------------------------------ helpers

def draft_to_dict(row) -> dict:
    d = dict(row)
    if d.get("media_path"):
        d["media_url"] = f"/media/{Path(d['media_path']).name}"
    if d.get("variants"):
        try:
            d["variants"] = json.loads(d["variants"])
        except (json.JSONDecodeError, TypeError):
            d["variants"] = {}
    else:
        d["variants"] = {}
    return d


def schedule_iso(dt_local: str) -> str:
    """Convert 'YYYY-MM-DDTHH:MM' (Asia/Tehran local) to ISO UTC."""
    from datetime import datetime, timedelta, timezone as tz
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})", dt_local or "")
    if not m:
        raise HTTPException(400, "فرمت زمان نامعتبر است (YYYY-MM-DDTHH:MM)")
    y, mo, d, h, mi = map(int, m.groups())
    try:
        local = datetime(y, mo, d, h, mi)
    except ValueError:
        raise HTTPException(400, "تاریخ/ساعت نامعتبر است")
    # Asia/Tehran: UTC+03:30 (no DST since 2022)
    offset = timedelta(hours=3, minutes=30)
    return (local - offset).replace(tzinfo=tz.utc).isoformat(timespec="seconds")


def tg_api(method: str, **params):
    url = f"{TELEGRAM_API}/bot{_bot_token()}/{method}"
    try:
        r = httpx.post(url, json=params, timeout=15, trust_env=False)
        data = r.json()
    except Exception as exc:
        raise HTTPException(502, f"خطای ارتباط با تلگرام: {exc}")
    if not data.get("ok"):
        raise HTTPException(400, f"تلگرام: {data.get('description', 'خطای نامشخص')}")
    return data["result"]


# ------------------------------------------------------------------ AI

AI_SYSTEM = (
    "تو دستیار تولید محتوای کانال تلگرامی VoidFeed هستی. "
    "پست‌های کوتاه، جذاب و مناسب تلگرام می‌نویسی. "
    "فقط متن پست را برگردان، بدون توضیح اضافه، بدون گیومه اطراف کل متن. "
    "اگر مناسب بود از ایموجی استفاده کن و از هشتگ‌های مرتبط در انتها بهره ببر."
)

async def ai_chat(messages: list[dict]) -> str:
    ai_base, ai_key, ai_model, ai_fallbacks = _ai_cfg()
    if not (ai_base and ai_key):
        raise HTTPException(
            503,
            "هوش مصنوعی تنظیم نشده است. AI_API_BASE و AI_API_KEY را در .env بگذار.",
        )
    models = ([ai_model] if ai_model else []) + ai_fallbacks
    if not models:
        models = ["deepseek-ai/DeepSeek-V4-Flash-0731", "zai-org/GLM-5.3-Flash"]
    last_error = None
    async with httpx.AsyncClient(timeout=90, trust_env=False) as client:
        for model in models:
            for attempt in range(2):
                try:
                    r = await client.post(
                        f"{ai_base}/chat/completions",
                        headers={"Authorization": f"Bearer {ai_key}"},
                        json={"model": model, "messages": messages, "temperature": 0.8},
                    )
                    data = r.json()
                    if r.status_code == 200 and data.get("choices"):
                        return data["choices"][0]["message"]["content"].strip()
                    last_error = f"{model}: {data.get('error', {}).get('message', r.status_code)}"
                except Exception as exc:
                    last_error = f"{model}: {exc}"
                if attempt == 0:
                    await asyncio.sleep(3)  # async: never block the event loop
    raise HTTPException(502, f"تولید محتوا ناموفق بود. {last_error}")


# ------------------------------------------------------------------ API

@app.get("/api/me")
def api_me(authorization: str | None = Header(None)):
    user = require_admin(authorization)
    ai_base, ai_key, ai_model, ai_fallbacks = _ai_cfg()
    return {
        "user": user,
        "ai_ready": bool(ai_base and ai_key),
        "ai_model": ai_model or (ai_fallbacks[0] if ai_fallbacks else None),
        "stats": db.stats(),
    }


@app.get("/api/drafts")
def api_drafts(authorization: str | None = Header(None), status: str | None = Query(None),
               limit: int = 200):
    require_admin(authorization)
    if status and status not in db.STATUSES:
        raise HTTPException(400, "وضعیت نامعتبر")
    return [draft_to_dict(r) for r in db.list_drafts(status, min(limit, 500))]


@app.get("/api/drafts/{draft_id}")
def api_draft(draft_id: int, authorization: str | None = Header(None)):
    require_admin(authorization)
    row = db.get_draft(draft_id)
    if not row:
        raise HTTPException(404, "پیش‌نویس پیدا نشد")
    return draft_to_dict(row)


@app.post("/api/drafts")
async def api_create_draft(authorization: str | None = Header(None),
                           payload: dict = Body(default={})):
    require_admin(authorization)
    content = (payload.get("content") or "").strip()
    channel_id = payload.get("channel_id")
    media_url = payload.get("media_url")
    media_kind = payload.get("media_kind")
    scheduled_at = payload.get("scheduled_at")
    status = payload.get("status", "draft")
    variants = payload.get("variants") or {}
    if not content and not media_url:
        raise HTTPException(400, "متن یا تصویر لازم است")
    if len(content) > MAX_TEXT:
        raise HTTPException(400, f"متن بیش از حد طولانی است (حداکثر {MAX_TEXT})")
    media_path = _media_path_from_url(media_url)
    if media_path:
        if len(content) > 1000:
            raise HTTPException(400, "متن همراه رسانه حداکثر ۱۰۰۰ نویسه (کپشن تلگرام)")
        if not media_kind:
            media_kind = "video" if media_path.endswith(
                (".mp4", ".mov", ".webm")) else "photo"
    if status not in ("draft", "approved", "scheduled"):
        status = "draft"
    sched = schedule_iso(scheduled_at) if scheduled_at else None
    if status == "scheduled" and not sched:
        raise HTTPException(400, "برای زمان‌بندی، زمان لازم است")
    errors = _validate_variants(variants)
    if errors:
        raise HTTPException(400, "؛ ".join(errors))
    draft_id = db.save_draft(content, channel_id=channel_id, media_path=media_path,
                             media_kind=media_kind if media_path else None,
                             source="studio", status="draft")
    if variants:
        db.update_draft(draft_id, variants=json.dumps(variants, ensure_ascii=False))
    if status == "scheduled":
        db.set_draft_status(draft_id, "scheduled", admin_id=_admin_id(), scheduled_at=sched)
    elif status == "approved":
        db.set_draft_status(draft_id, "approved", admin_id=_admin_id())
    return draft_to_dict(db.get_draft(draft_id))


def _validate_variants(variants: dict) -> list[str]:
    errors = []
    for network, text in (variants or {}).items():
        if network not in NETWORK_SPECS:
            continue
        err = _validate_network_text((text or "").strip(), network)
        if err:
            errors.append(err)
    return errors


def _media_path_from_url(media_url: str | None) -> str | None:
    if not media_url:
        return None
    name = Path(urllib.parse.urlparse(media_url).path).name
    if "/" in name or ".." in name:
        raise HTTPException(400, "مسیر تصویر نامعتبر است")
    p = db.MEDIA_DIR / name
    if not p.is_file():
        raise HTTPException(404, "تصویر پیدا نشد؛ دوباره آپلود کن")
    return str(p)


@app.put("/api/drafts/{draft_id}")
async def api_update_draft(draft_id: int, authorization: str | None = Header(None),
                           payload: dict = Body(default={})):
    require_admin(authorization)
    row = db.get_draft(draft_id)
    if not row:
        raise HTTPException(404, "پیش‌نویس پیدا نشد")
    if row["status"] in ("published",):
        raise HTTPException(400, "پست منتشرشده قابل ویرایش نیست")
    fields = {}
    content = payload.get("content")
    channel_id = payload.get("channel_id")
    media_url = payload.get("media_url")
    scheduled_at = payload.get("scheduled_at")
    if content is not None:
        content = content.strip()
        if len(content) > MAX_TEXT:
            raise HTTPException(400, f"متن حداکثر {MAX_TEXT} نویسه")
        if row["media_path"] and len(content) > 1000:
            raise HTTPException(400, "متن همراه تصویر حداکثر ۱۰۰۰ نویسه")
        if not content and not row["media_path"]:
            raise HTTPException(400, "متن یا تصویر لازم است")
        fields["content"] = content
    if channel_id is not None:
        fields["channel_id"] = channel_id
    if media_url is not None:
        fields["media_path"] = _media_path_from_url(media_url)
        if fields["media_path"]:
            fields["media_kind"] = (
                payload.get("media_kind")
                or ("video" if fields["media_path"].endswith((".mp4", ".mov", ".webm"))
                    else "photo")
            )
        else:
            fields["media_kind"] = None
    variants = payload.get("variants")
    if variants is not None:
        errors = _validate_variants(variants)
        if errors:
            raise HTTPException(400, "؛ ".join(errors))
        fields["variants"] = json.dumps(variants, ensure_ascii=False) if variants else None
    db.update_draft(draft_id, **fields)
    if scheduled_at:
        db.set_draft_status(draft_id, "scheduled", admin_id=_admin_id(),
                            scheduled_at=schedule_iso(scheduled_at))
    return draft_to_dict(db.get_draft(draft_id))


@app.post("/api/drafts/{draft_id}/{action}")
async def api_draft_action(draft_id: int, action: str,
                           authorization: str | None = Header(None),
                           payload: dict = Body(default={})):
    require_admin(authorization)
    scheduled_at = payload.get("scheduled_at")
    channel_id = payload.get("channel_id")
    row = db.get_draft(draft_id)
    if not row:
        raise HTTPException(404, "پیش‌نویس پیدا نشد")

    if action == "approve":
        if row["status"] in ("published",):
            raise HTTPException(400, "پست منتشر شده است")
        db.set_draft_status(draft_id, "approved", admin_id=_admin_id())
    elif action == "reject":
        if row["status"] == "published":
            raise HTTPException(400, "پست منتشر شده است")
        db.set_draft_status(draft_id, "rejected", admin_id=_admin_id())
    elif action == "schedule":
        if row["status"] == "published":
            raise HTTPException(400, "پست منتشر شده است")
        if not scheduled_at:
            raise HTTPException(400, "زمان لازم است")
        target_channel = channel_id or row["channel_id"] or (
            db.get_default_channel()["id"] if db.get_default_channel() else None)
        if not target_channel:
            raise HTTPException(400, "اول کانال را در تب کانال‌ها اضافه کن")
        if not row["media_path"] and not (row["content"] or "").strip():
            raise HTTPException(400, "محتوای خالی منتشر نمی‌شود")
        db.update_draft(draft_id, channel_id=target_channel)
        db.set_draft_status(draft_id, "scheduled", admin_id=_admin_id(),
                            scheduled_at=schedule_iso(scheduled_at))
        db.add_publish_event(draft_id, target_channel, "scheduled",
                             scheduled_at=schedule_iso(scheduled_at))
    elif action == "unschedule":
        db.set_draft_status(draft_id, "approved", admin_id=_admin_id())
        db.add_publish_event(draft_id, row["channel_id"] if "channel_id" in row.keys() else None,
                             "unscheduled")
    elif action == "publish":
        if row["status"] == "published":
            raise HTTPException(409, "پست منتشر شده است")
        target_channel = channel_id or row["channel_id"]
        if not target_channel:
            default = db.get_default_channel()
            target_channel = default["id"] if default else None
        if not target_channel:
            raise HTTPException(400, "اول کانال را در تب کانال‌ها اضافه کن")
        if not row["media_path"] and not (row["content"] or "").strip():
            raise HTTPException(400, "محتوای خالی منتشر نمی‌شود")
        # to_thread: keep the event loop free during the (slow) media upload
        result = await asyncio.to_thread(_publish_now, row, target_channel)
        if result is not True:
            raise HTTPException(502, result)
    elif action == "delete":
        db.delete_draft(draft_id)
        return {"ok": True, "deleted": draft_id}
    else:
        raise HTTPException(404, "عملیات نامعتبر")
    return draft_to_dict(db.get_draft(draft_id))


MAX_PUBLISH_ATTEMPTS = 3


def _apply_publish_result(row, ok: bool, channel_id: int,
                          triggered_by: str, error: str | None = None) -> bool:
    """Unified publish outcome for all paths (studio / bot / news).

    - success: status=published, publish_error cleared, attempts reset, event.
    - failure: publish_error recorded, attempts incremented, 'failed' event;
      after MAX_PUBLISH_ATTEMPTS the draft moves to publish_failed (still
      retryable). Cancel status is preserved so the user can retry safely.
    """
    did = row["id"]
    row = dict(row)  # sqlite3.Row → dict
    if ok:
        db.set_draft_status(did, "published", admin_id=_admin_id())
        db.update_draft(did, published_at=db.utc_now(), channel_id=channel_id,
                        publish_error=None, attempts=0)
        db.add_publish_event(did, channel_id, "published", triggered_by=triggered_by)
        return True
    attempts = row.get("attempts", 0) + 1
    db.update_draft(did, publish_error=(error or "")[:500], attempts=attempts)
    db.add_publish_event(did, channel_id, "failed",
                         details=(error or "")[:300], triggered_by=triggered_by)
    if attempts >= MAX_PUBLISH_ATTEMPTS:
        db.update_draft(did, status="publish_failed")
    return False


def _publish_now(row, channel_id: int) -> bool | str:
    """Publish immediately from the studio process (text/photo via Bot API)."""
    channel = db.get_channel(channel_id)
    if not channel:
        return "کانال پیدا نشد"

    # Pre-flight Telegram media validation — never send what the API rejects.
    _cols = row.keys()
    media_err = validate_media(
        row["media_kind"] if "media_kind" in _cols else None,
        row["media_path"] if "media_path" in _cols else None)
    if media_err:
        _apply_publish_result(row, False, channel_id, "studio", media_err)
        return media_err

    signature = ""
    if db.get_setting("signature_enabled", "1") == "1":
        signature = db.get_setting("signature_text", "") or ""
    text = (row["content"] or "").strip()
    if signature and signature not in text:
        text = (text + "\n\n" + signature).strip() if text else signature
    try:
        if row["media_path"] and Path(row["media_path"]).is_file():
            with open(row["media_path"], "rb") as fh:
                if row["media_kind"] == "video":
                    r = httpx.post(
                        f"{TELEGRAM_API}/bot{_bot_token()}/sendVideo",
                        data={"chat_id": channel["chat_id"],
                              "caption": text[:1024] or None,
                              "supports_streaming": "true"},
                        files={"video": fh},
                        timeout=120,
                        trust_env=False,
                    )
                else:
                    r = httpx.post(
                        f"{TELEGRAM_API}/bot{_bot_token()}/sendPhoto",
                        data={"chat_id": channel["chat_id"], "caption": text[:1024] or None},
                        files={"photo": fh},
                        timeout=60,
                        trust_env=False,
                    )
        else:
            r = httpx.post(
                f"{TELEGRAM_API}/bot{_bot_token()}/sendMessage",
                json={"chat_id": channel["chat_id"], "text": text[:4096]},
                timeout=30,
                trust_env=False,
            )
        data = r.json()
    except Exception as exc:
        err = f"connection error: {type(exc).__name__}: {exc}"
        _apply_publish_result(row, False, channel_id, "studio", err)
        return f"خطای ارتباط: {exc}"
    if data.get("ok"):
        _apply_publish_result(row, True, channel_id, "studio")
        return True
    err = data.get("description", "خطای نامشخص تلگرام")
    _apply_publish_result(row, False, channel_id, "studio", err)
    return err


# ------------------------------------------------------------------ channels

@app.get("/api/channels")
def api_channels(authorization: str | None = Header(None)):
    require_admin(authorization)
    return [dict(r) for r in db.list_channels()]


@app.post("/api/channels")
async def api_add_channel(authorization: str | None = Header(None),
                          payload: dict = Body(default={})):
    require_admin(authorization)
    ref = (payload.get("ref") or "").strip().lstrip("@")
    ref = ref.split("https://t.me/")[-1].split("/")[-1]
    if not re.fullmatch(r"[A-Za-z0-9_]{4,64}", ref or ""):
        raise HTTPException(400, "آیدی کانال نامعتبر است (@username)")
    try:
        chat = tg_api("getChat", chat_id=f"@{ref}")
    except HTTPException as exc:
        raise HTTPException(400, f"کانال پیدا نشد: {exc.detail}")
    bot_user_id = int(_bot_token().split(":")[0])
    member = tg_api("getChatMember", chat_id=chat["id"], user_id=bot_user_id)
    if member.get("status") not in ("administrator", "creator"):
        raise HTTPException(
            400,
            "بات باید ادمین کانال باشد. اول @VoidFeedbot را ادمین کانال کن و بعد دوباره امتحان کن.",
        )
    channel_id = db.add_channel(chat["id"], chat.get("title", ref), chat.get("username"))
    return {"ok": True, "channel": dict(db.get_channel(channel_id))}


@app.delete("/api/channels/{channel_id}")
def api_remove_channel(channel_id: int, authorization: str | None = Header(None)):
    require_admin(authorization)
    return {"ok": db.remove_channel(channel_id)}


@app.post("/api/channels/{channel_id}/default")
def api_default_channel(channel_id: int, authorization: str | None = Header(None)):
    require_admin(authorization)
    if not db.set_default_channel(channel_id):
        raise HTTPException(404, "کانال پیدا نشد")
    return {"ok": True}


# ------------------------------------------------------------------ media

@app.post("/api/media")
async def api_upload_media(authorization: str | None = Header(None),
                           file: UploadFile = File(...)):
    require_admin(authorization)
    ext = Path(file.filename or "").suffix.lower()
    if ext in ALLOWED_VIDEO_EXT:
        kind, limit = "video", MAX_VIDEO_BYTES
        limit_label = "۵۰ مگابایت"
    elif ext in ALLOWED_PHOTO_EXT:
        kind, limit = "photo", MAX_PHOTO_BYTES
        limit_label = "۲۰ مگابایت"
    else:
        raise HTTPException(400, "فرمت باید jpg/png/webp یا mp4/mov/webm باشد")
    data = await file.read()
    if len(data) > limit:
        raise HTTPException(400, f"حجم فایل حداکثر {limit_label} است")
    name = f"{int(time.time())}_{secrets.token_hex(6)}{ext}"
    path = db.MEDIA_DIR / name
    path.write_bytes(data)
    os.chmod(path, 0o600)
    db.add_media_item(name, original_name=(file.filename or "")[:200],
                      kind=kind, size_bytes=len(data), mime=file.content_type or "")
    return {"url": f"/media/{name}", "kind": kind, "bytes": len(data)}


@app.get("/api/media/library")
def api_media_library(authorization: str | None = Header(None)):
    require_admin(authorization)
    out = []
    for r in db.list_media_items():
        d = dict(r)
        d["url"] = f"/media/{d['filename']}"
        out.append(d)
    return out


@app.put("/api/media/library/{item_id}")
def api_media_library_update(item_id: int, authorization: str | None = Header(None),
                             payload: dict = Body(default={})):
    require_admin(authorization)
    if not db.get_media_item(item_id):
        raise HTTPException(404, "آیتم پیدا نشد")
    alt_text = str(payload.get("alt_text", ""))[:300]
    caption = str(payload.get("caption", ""))[:500]
    db.update_media_item(item_id, alt_text=alt_text, caption=caption)
    return {"ok": True}


@app.delete("/api/media/library/{item_id}")
def api_media_library_delete(item_id: int, authorization: str | None = Header(None)):
    require_admin(authorization)
    row = db.get_media_item(item_id)
    if not row:
        raise HTTPException(404, "آیتم پیدا نشد")
    if db.media_referenced(row["filename"]):
        raise HTTPException(409, "این فایل در پست‌ها استفاده شده و قابل حذف نیست")
    (db.MEDIA_DIR / row["filename"]).unlink(missing_ok=True)
    db.delete_media_item(item_id)
    return {"ok": True}


@app.get("/api/templates")
def api_templates(authorization: str | None = Header(None)):
    require_admin(authorization)
    return [dict(r) for r in db.list_templates()]


@app.post("/api/templates")
def api_templates_create(authorization: str | None = Header(None),
                         payload: dict = Body(default={})):
    require_admin(authorization)
    name = str(payload.get("name", "")).strip()[:100]
    body = str(payload.get("body", "")).strip()
    if not name or not body:
        raise HTTPException(400, "نام و متن قالب لازم است")
    tid = db.save_template(name, body)
    return {"ok": True, "id": tid}


@app.put("/api/templates/{template_id}")
def api_templates_update(template_id: int, authorization: str | None = Header(None),
                         payload: dict = Body(default={})):
    require_admin(authorization)
    if not db.get_template(template_id):
        raise HTTPException(404, "قالب پیدا نشد")
    name = str(payload.get("name", "")).strip()[:100]
    body = str(payload.get("body", "")).strip()
    if not name or not body:
        raise HTTPException(400, "نام و متن قالب لازم است")
    db.save_template(name, body, template_id)
    return {"ok": True}


@app.delete("/api/templates/{template_id}")
def api_templates_delete(template_id: int, authorization: str | None = Header(None)):
    require_admin(authorization)
    if not db.delete_template(template_id):
        raise HTTPException(404, "قالب پیدا نشد")
    return {"ok": True}


@app.get("/media/{name}")
def api_media(name: str, authorization: str | None = Header(None)):
    require_admin(authorization)
    if "/" in name or ".." in name:
        raise HTTPException(400, "نام فایل نامعتبر")
    path = db.MEDIA_DIR / name
    if not path.is_file():
        raise HTTPException(404, "پیدا نشد")
    return FileResponse(path)


# ------------------------------------------------------- media generation

@app.get("/api/platforms")
def api_platforms():
    import mediagen
    return {k: {"w": v[0], "h": v[1], "label": v[2]} for k, v in mediagen.PLATFORM_SIZES.items()}


@app.post("/api/media/generate")
async def api_media_generate(authorization: str | None = Header(None),
                             payload: dict = Body(default={})):
    """Generate a branded image or an animated video for a platform."""
    require_admin(authorization)
    import mediagen
    text = (payload.get("text") or "").strip()
    platform = payload.get("platform", "telegram")
    kind = payload.get("kind", "photo")
    theme = payload.get("theme", "news")
    source = (payload.get("source") or "").strip()
    seconds = payload.get("seconds", 8)
    base_url = payload.get("base_media_url")
    if platform not in mediagen.PLATFORM_SIZES:
        raise HTTPException(400, "پلتفرم نامعتبر")
    if kind not in ("photo", "video"):
        raise HTTPException(400, "kind باید photo یا video باشد")
    if kind == "photo" and not text:
        raise HTTPException(400, "متن برای تولید تصویر لازم است")
    try:
        if kind == "video":
            if base_url:
                base = _media_path_from_url(base_url)
            else:
                base = mediagen.generate_image(text, platform, theme, source)
            path = mediagen.generate_video(base, platform, int(seconds))
            kind = "video"
        else:
            path = mediagen.generate_image(text, platform, theme, source)
            kind = "photo"
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except (RuntimeError, FileNotFoundError) as exc:
        raise HTTPException(502, f"تولید رسانه ناموفق بود: {exc}")
    return {"url": f"/media/{Path(path).name}", "kind": kind, "platform": platform}


# ------------------------------------------------------------------ plan

@app.get("/api/plan")
def api_plan(authorization: str | None = Header(None), month: str = ""):
    require_admin(authorization)
    if not re.fullmatch(r"\d{4}-\d{2}", month or ""):
        raise HTTPException(400, "ماه نامعتبر (YYYY-MM)")
    rows = db.plan_month(month)
    out = []
    for r in rows:
        d = dict(r)
        when = d.get("scheduled_at") or d.get("published_at") or ""
        d["day"] = when[8:10] if when[:7] == month else None
        out.append(d)
    return out


@app.get("/api/history")
def api_history(authorization: str | None = Header(None),
                event: str | None = Query(None), limit: int = 100):
    require_admin(authorization)
    if event and event not in ("scheduled", "published", "failed", "unscheduled"):
        raise HTTPException(400, "event نامعتبر است")
    rows = db.list_publish_events(event, min(limit, 500))
    out = []
    for r in rows:
        d = dict(r)
        ch = db.get_channel(d["channel_id"]) if d.get("channel_id") else None
        draft = db.get_draft(d["draft_id"]) if d.get("draft_id") else None
        d["channel_title"] = ch["title"] if ch else None
        d["draft_snippet"] = (draft["content"] or "")[:120] if draft else None
        out.append(d)
    return out


# ------------------------------------------------------------------ AI endpoints

@app.get("/api/ai/status")
def api_ai_status(authorization: str | None = Header(None)):
    require_admin(authorization)
    base, key, model, fallbacks = _ai_cfg()
    host = ""
    if base:
        try:
            parsed = urllib.parse.urlsplit(base)
            host = parsed.hostname or ""
        except Exception:
            host = ""
    return {
        "configured": bool(base and key),
        "key_set": bool(key),
        "base_host": host,
        "model": model or "",
        "fallbacks": fallbacks,
        "ready": bool(base and key),
    }


@app.post("/api/ai/test")
async def api_ai_test(authorization: str | None = Header(None)):
    require_admin(authorization)
    base, key, model, _ = _ai_cfg()
    if not (base and key):
        raise HTTPException(409, "هوش مصنوعی تنظیم نشده است")
    try:
        async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
            r = await client.get(
                f"{base}/models", headers={"Authorization": f"Bearer {key}"})
        if r.status_code < 400:
            return {"ok": True, "status": r.status_code}
        # 4xx/5xx: report sanitized status only, never the response body
        return {"ok": False, "status": r.status_code,
                "error": f"HTTP {r.status_code}"}
    except Exception as exc:
        logger.warning("ai test connection failed: %s", type(exc).__name__)
        return {"ok": False, "error": "connection failed"}


@app.post("/api/ai/generate")
async def api_ai_generate(authorization: str | None = Header(None),
                          payload: dict = Body(default={})):
    require_admin(authorization)
    topic = (payload.get("topic") or "").strip()
    tone = payload.get("tone", "friendly")
    length = payload.get("length", "medium")
    if not topic:
        raise HTTPException(400, "موضوع پست را بنویس")
    length_map = {"short": "کوتاه (حدود ۳۰ کلمه)", "medium": "متوسط (حدود ۸۰ کلمه)", "long": "بلند (حدود ۱۵۰ کلمه)"}
    tone_map = {"friendly": "خودمونی و صمیمی", "formal": "رسمی و حرفه‌ای",
                "funny": "طنز و بامزه", "promo": "تبلیغاتی و هیجانی",
                "news": "خبری و اطلاع‌رسانی"}
    prompt = (
        f"یک پست تلگرامی به زبان فارسی درباره‌ی موضوع زیر بنویس.\n"
        f"موضوع: {topic}\n"
        f"لحن: {tone_map.get(tone, 'صمیمی')}\n"
        f"طول: {length_map.get(length, 'متوسط')}\n"
        "پست را آماده انتشار بنویس."
    )
    text = await ai_chat([{"role": "system", "content": AI_SYSTEM},
                          {"role": "user", "content": prompt}])
    _, _, ai_model, ai_fallbacks = _ai_cfg()
    return {"text": text, "model": ai_model or (ai_fallbacks[0] if ai_fallbacks else "default")}


@app.post("/api/ai/rewrite")
async def api_ai_rewrite(authorization: str | None = Header(None),
                         payload: dict = Body(default={})):
    require_admin(authorization)
    content = (payload.get("content") or "").strip()
    mode = payload.get("mode", "improve")
    if not content:
        raise HTTPException(400, "متنی برای بازنویسی نیست")
    modes = {
        "improve": "این پست تلگرامی را روان‌تر و جذاب‌تر بازنویسی کن؛ معنا را حفظ کن:",
        "shorten": "این پست را تا نصف کوتاه کن بدون از دست دادن پیام اصلی:",
        "emoji": "این پست را با ایموجی‌های مناسب و جذاب بازنویسی کن؛ معنا را حفظ کن:",
        "formal": "این پست را با لحن رسمی‌تر بازنویسی کن:",
        "casual": "این پست را با لحن خودمونی و صمیمی بازنویسی کن:",
    }
    prompt = f"{modes.get(mode, modes['improve'])}\n\n{content}"
    text = await ai_chat([{"role": "system", "content": AI_SYSTEM},
                          {"role": "user", "content": prompt}])
    return {"text": text}


@app.post("/api/ai/format")
async def api_ai_format(authorization: str | None = Header(None),
                        payload: dict = Body(default={})):
    """Reformat a post for a specific network's limits and style."""
    require_admin(authorization)
    content = (payload.get("content") or "").strip()
    network = payload.get("network", "telegram")
    spec = NETWORK_SPECS.get(network)
    if not spec:
        raise HTTPException(400, "شبکه نامعتبر")
    if not content:
        raise HTTPException(400, "متنی نیست")
    style = {
        "telegram": "پست تلگرامی جذاب با ایموجی و هشتگ",
        "x": "توییت کوتاه و punchy، حداکثر ۲۸۰ نویسه، بدون هشتگ اضافی",
        "instagram": "کپشن اینستاگرام با خطوط کوتاه و هشتگ‌های مرتبط",
        "youtube": "توضیحات ویدیوی یوتیوب با عنوان جذاب در خط اول",
        "facebook": "پست فیس‌بوک خودمونی و داستانی",
        "tiktok": "کپشن کوتاه تیک‌تاک با هشتگ ترند",
    }.get(network, "پست کوتاه")
    prompt = (
        f"این متن را برای {spec['label']} بازنویسی کن.\n"
        f"سبک: {style}\n"
        f"حداکثر نویسه: {spec['text_max']} — از این حد بلندتر نشو.\n"
        f"متن اصلی:\n{content}"
    )
    text = await ai_chat([
        {"role": "system",
         "content": "تو دستیار تولید محتوای VoidFeed هستی. فقط متن نهایی را برگردان، بدون توضیح و بدون گیومه."},
        {"role": "user", "content": prompt},
    ])
    return {"text": text, "network": network, "length": len(text)}

NETWORK_SPECS = {
    "telegram": {
        "label": "Telegram", "text_max": 4096, "caption_max": 1024,
        "photo_max_mb": 10, "video_max_mb": 50, "video_max_min": None,
        "photos_max": 10, "aspect": "هر نسبتی", "note": "انتشار مستقیم توسط بات",
    },
    "x": {
        "label": "X (Twitter)", "text_max": 280, "caption_max": 280,
        "photo_max_mb": 5, "video_max_mb": 512, "video_max_min": 2.33,
        "photos_max": 4, "aspect": "16:9 یا 1:1", "note": "خروجی متن آماده کپی",
    },
    "instagram": {
        "label": "Instagram", "text_max": 2200, "caption_max": 2200,
        "photo_max_mb": 8, "video_max_mb": 100, "video_max_min": 90 / 60,
        "photos_max": 10, "aspect": "9:16، 4:5 یا 1:1", "note": "خروجی متن آماده کپی",
    },
    "youtube": {
        "label": "YouTube", "text_max": 5000, "caption_max": 5000,
        "photo_max_mb": 2, "video_max_mb": 256000, "video_max_min": 720,
        "photos_max": 1, "aspect": "16:9", "note": "عنوان ۱۰۰ نویسه + توضیحات",
    },
    "facebook": {
        "label": "Facebook", "text_max": 63206, "caption_max": 63206,
        "photo_max_mb": 30, "video_max_mb": 4000, "video_max_min": 240,
        "photos_max": 10, "aspect": "آزاد", "note": "خروجی متن آماده کپی",
    },
    "tiktok": {
        "label": "TikTok", "text_max": 2200, "caption_max": 2200,
        "photo_max_mb": 20, "video_max_mb": 500, "video_max_min": 10,
        "photos_max": 1, "aspect": "9:16", "note": "خروجی متن آماده کپی",
    },
}


@app.get("/api/networks")
def api_networks():
    return NETWORK_SPECS


def _validate_network_text(text: str, network: str) -> str | None:
    spec = NETWORK_SPECS.get(network)
    if not spec:
        return None
    limit = spec["text_max"]
    if len(text) > limit:
        return f"{spec['label']}: حداکثر {limit} نویسه (الان {len(text)})"
    return None


@app.get("/api/mod/words")
def api_mod_words(authorization: str | None = Header(None)):
    require_admin(authorization)
    import moderator as _mod
    out = {k: [] for k in _mod.CAT_LABELS}
    for row in db.mod_words_all():
        out.setdefault(row["category"], []).append(
            {"term": row["term"], "is_regex": bool(row["is_regex"])}
        )
    return out


@app.post("/api/mod/words")
def api_mod_word_add(authorization: str | None = Header(None),
                     payload: dict = Body(default={})):
    require_admin(authorization)
    import moderator as _mod
    category = payload.get("category", "")
    term = (payload.get("term") or "").strip()
    is_regex = bool(payload.get("is_regex"))
    if category not in _mod.CAT_LABELS:
        raise HTTPException(400, "دستهٔ نامعتبر")
    if not term:
        raise HTTPException(400, "واژه خالی است")
    if is_regex or term.startswith("re:"):
        pattern = term[3:] if term.startswith("re:") else term
        try:
            re.compile(pattern)
        except re.error as exc:
            raise HTTPException(400, f"Regex نامعتبر: {exc}")
    ok = db.mod_word_add(category, term, is_regex=is_regex)
    if not ok:
        raise HTTPException(400, "این واژه قبلاً ثبت شده است")
    _mod.invalidate_cache()
    db.log_mod_action(0, None, "word_add", reason=category, detail=term)
    return {"ok": True}


@app.delete("/api/mod/words")
def api_mod_word_remove(authorization: str | None = Header(None),
                        payload: dict = Body(default={})):
    require_admin(authorization)
    import moderator as _mod
    category = payload.get("category", "")
    term = (payload.get("term") or "").strip()
    ok = db.mod_word_remove(category, term)
    _mod.invalidate_cache()
    db.log_mod_action(0, None, "word_remove", reason=category, detail=term)
    return {"ok": ok}


@app.get("/api/mod/chats")
def api_mod_chats(authorization: str | None = Header(None)):
    require_admin(authorization)
    import moderator as _mod
    out = []
    for c in db.list_channels():
        if c["kind"] == "channel":
            continue
        out.append({
            "id": c["id"], "chat_id": c["chat_id"], "title": c["title"],
            "username": c["username"],
            "enabled": db.get_setting(f"mod:{c['chat_id']}", "1") == "1",
            "stats": db.mod_stats(c["chat_id"]),
        })
    return out


@app.post("/api/mod/chats/{chat_id}/toggle")
def api_mod_toggle(chat_id: int, authorization: str | None = Header(None)):
    require_admin(authorization)
    current = db.get_setting(f"mod:{chat_id}", "1")
    db.set_setting(f"mod:{chat_id}", "0" if current == "1" else "1")
    return {"enabled": db.get_setting(f"mod:{chat_id}", "1") == "1"}


@app.get("/api/mod/log")
def api_mod_log(authorization: str | None = Header(None), limit: int = 50):
    require_admin(authorization)
    return [dict(r) for r in db.mod_log_recent(limit=min(limit, 200))]


@app.get("/api/mod/banned")
def api_mod_banned(authorization: str | None = Header(None)):
    require_admin(authorization)
    return [dict(r) for r in db.mod_banned_list()]


@app.post("/api/mod/banned/{chat_id}/{user_id}/unban")
def api_mod_unban(chat_id: int, user_id: int,
                  authorization: str | None = Header(None)):
    require_admin(authorization)
    db.unban_user(chat_id, user_id)
    db.log_mod_action(chat_id, user_id, "unban", reason="از استودیو")
    return {"ok": True}


@app.get("/api/settings")
def api_get_settings(authorization: str | None = Header(None)):
    require_admin(authorization)
    return {
        "signature_enabled": db.get_setting("signature_enabled", "1"),
        "signature_text": db.get_setting("signature_text", ""),
    }


@app.put("/api/settings")
def api_put_settings(authorization: str | None = Header(None),
                     payload: dict = Body(default={})):
    require_admin(authorization)
    signature_enabled = payload.get("signature_enabled")
    signature_text = payload.get("signature_text")
    if signature_enabled is not None:
        db.set_setting("signature_enabled", "1" if signature_enabled == "1" else "0")
    if signature_text is not None:
        db.set_setting("signature_text", signature_text[:300])
    return api_get_settings(authorization)


NEWS_DEFAULT_SOURCES = [
    {"name": "Variety", "url": "https://variety.com/feed/", "cat": "cinema"},
    {"name": "Deadline", "url": "https://deadline.com/feed/", "cat": "cinema"},
    {"name": "ScreenRant", "url": "https://screenrant.com/feed/", "cat": "series"},
    {"name": "TVLine", "url": "https://tvline.com/feed/", "cat": "series"},
    {"name": "IGN", "url": "https://feeds.feedburner.com/ign/all", "cat": "games"},
    {"name": "GameSpot", "url": "https://www.gamespot.com/feeds/news/", "cat": "games"},
    {"name": "US Weekly", "url": "https://www.usmagazine.com/feed/", "cat": "celebs"},
    {"name": "Rolling Stone", "url": "https://www.rollingstone.com/feed/", "cat": "music"},
    {"name": "Billboard", "url": "https://www.billboard.com/feed/", "cat": "music"},
    {"name": "NME", "url": "https://www.nme.com/feed", "cat": "music"},
    {"name": "Film Music Reporter", "url": "https://filmmusicreporter.com/feed/", "cat": "music"},
    {"name": "ComicBook", "url": "https://comicbook.com/feed/", "cat": "rumor"},
    {"name": "Giant Freakin Robot", "url": "https://www.giantfreakinrobot.com/feed", "cat": "rumor"},
]


@app.get("/api/news/config")
def api_news_config(authorization: str | None = Header(None)):
    require_admin(authorization)
    import json as _json
    raw = db.get_setting("news_sources", "")
    try:
        sources = _json.loads(raw) if raw else NEWS_DEFAULT_SOURCES
    except Exception:
        sources = NEWS_DEFAULT_SOURCES
    return {
        "enabled": db.get_setting("news_enabled", "1") == "1",
        "interval_min": int(db.get_setting("news_interval_min", "30") or 30),
        "auto_publish": db.get_setting("news_auto_publish", "1") == "1",
        "sources": sources,
        "seen_count": db.news_seen_count(),
        "last_fetch": db.get_setting("news_last_fetch", ""),
        "last_error": db.get_setting("news_last_error", ""),
    }


@app.put("/api/news/config")
def api_news_config_put(authorization: str | None = Header(None),
                        payload: dict = Body(default={})):
    require_admin(authorization)
    import json as _json
    if "enabled" in payload:
        db.set_setting("news_enabled", "1" if payload["enabled"] else "0")
    if "interval_min" in payload:
        try:
            db.set_setting("news_interval_min",
                           str(max(10, min(240, int(payload["interval_min"])))))
        except (TypeError, ValueError):
            raise HTTPException(400, "interval نامعتبر است")
    if "auto_publish" in payload:
        db.set_setting("news_auto_publish", "1" if payload["auto_publish"] else "0")
    if "sources" in payload:
        clean = []
        for s in (payload["sources"] or [])[:20]:
            name = (s.get("name") or "").strip()[:60]
            url = (s.get("url") or "").strip()[:300]
            cat = (s.get("cat") or "news").strip()[:20]
            if name and url.startswith("http"):
                clean.append({"name": name, "url": url, "cat": cat})
        db.set_setting("news_sources", _json.dumps(clean, ensure_ascii=False))
    return api_news_config(authorization)


@app.post("/api/news/fetch_now")
async def api_news_fetch_now(authorization: str | None = Header(None)):
    require_admin(authorization)
    import newsbot
    result = await newsbot.run_once()
    if result.get("error"):
        raise HTTPException(502, result["error"])
    return result


# ------------------------------------------------------------------ static

@app.exception_handler(HTTPException)
async def http_exc_handler(request, exc: HTTPException):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@app.get("/healthz")
def healthz():
    return {"ok": True, "demo": DEMO}


app.mount("/static-assets", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html",
                        headers={"Cache-Control": "no-cache"})


@app.get("/app.js")
def app_js():
    return FileResponse(WEB_DIR / "app.js", media_type="text/javascript",
                        headers={"Cache-Control": "no-cache"})


@app.get("/app.css")
def app_css():
    return FileResponse(WEB_DIR / "app.css", media_type="text/css",
                        headers={"Cache-Control": "no-cache"})


@app.get("/telegram-web-app.js")
def tg_webapp_js():
    return FileResponse(WEB_DIR / "telegram-web-app.js", media_type="text/javascript")


# =====================================================================
# Brand Profile + Social Presence + Connections spec (DEV, additive)
# =====================================================================
# This section defines the VoidFeed brand identity, the ten-platform
# social presence registry, and a SAFE read-only "connections spec".
# It intentionally does NOT implement or revive OAuth; technical statuses
# are derived only from local config presence and never claim success.

BRAND = {
    "name_fa": "VoidFeed | خوراکِ خلأ",
    "name_en": "VoidFeed",
    "slogan_fa": "«جایی که داستان تمام می‌شود، ما تازه شروع می‌کنیم.»",
    "slogan_en": "Where stories end, we begin.",
    "email": "voidfeedteam@gmail.com",
    "logo": "/static-assets/wormhole.jpeg",
}
BRAND_DESC_FA_DEFAULT = (
    "VoidFeed یک آرشیو شخصی و پروژه رسانه‌ای خلاقانه است. اینجا درباره سینما، تلویزیون، "
    "ادبیات، موسیقی، بازی و ایده‌ها می‌نویسیم: تجربه‌های شخصی، پژوهش، مشاهده و تحلیل. "
    "ما ادعا نمی‌کنیم همه‌چیز را می‌دانیم یا منتقد حرفه‌ای هستیم؛ به رسانه‌های شخص ثالث "
    "مالکیتی نداریم و به سازندگان، دارندگان حقوق و ذکر منبع احترام می‌گذاریم."
)
BRAND_DESC_EN_DEFAULT = (
    "VoidFeed is a personal archive and creative media project. Here we write about "
    "cinema, television, literature, music, games and ideas: personal experience, "
    "research, observation and analysis. We do not claim to know everything or to be "
    "professional critics; we claim no ownership of third-party media, and we respect "
    "creators, rights holders and source attribution."
)

# Ten official platforms. url only when a public link is known; presence is
# NOT proof of verification — status is derived honestly (see _social_status).
PLATFORMS = [
    {"id": "telegram", "fa": "تلگرام", "en": "Telegram",
     "handle": "@FeedTheVoids", "display": None,
     "url": "https://t.me/FeedTheVoids", "asset": "telegram.svg"},
    {"id": "instagram", "fa": "اینستاگرام", "en": "Instagram",
     "handle": "@voidfeedmedia", "display": None,
     "url": "https://instagram.com/voidfeedmedia", "asset": "instagram.svg"},
    {"id": "facebook", "fa": "فیسبوک", "en": "Facebook",
     "handle": None, "display": "TheVoidFeedMedia",
     "url": "https://facebook.com/TheVoidFeedMedia", "asset": "facebook.svg"},
    {"id": "youtube", "fa": "یوتیوب", "en": "YouTube",
     "handle": "@voidfeedmedia", "display": None,
     "url": "https://youtube.com/@voidfeedmedia", "asset": "youtube.svg"},
    {"id": "x", "fa": "ایکس (توییتر)", "en": "X (Twitter)",
     "handle": "@VoidFeedMedia", "display": None,
     "url": "https://x.com/VoidFeedMedia", "asset": "x.svg",
     "asset_light": "x.svg", "asset_dark": "x-white.svg"},
    {"id": "tiktok", "fa": "تیک‌تاک", "en": "TikTok",
     "handle": "@voidfeedmedia", "display": None,
     "url": "https://www.tiktok.com/@voidfeedmedia", "asset": "tiktok-symbol.svg",
     "asset_note": "icon-only variant extracted from official wordmark artwork"},
    {"id": "quora", "fa": "کورا", "en": "Quora",
     "handle": None, "display": "Void Feed Media",
     "url": "https://www.quora.com/profile/Void-Feed-Media", "asset": "quora.svg"},
    {"id": "github", "fa": "گیت‌هاب", "en": "GitHub",
     "handle": None, "display": "voidfeedmedia",
     "url": "https://github.com/voidfeedmedia", "asset": "github.svg",
     "asset_light": "github.svg", "asset_dark": "github-white.svg"},
    {"id": "discord", "fa": "دیسکورد", "en": "Discord",
     "handle": None, "display": "VoidFeed.media", "profile_type": "user_profile",
     "url": "https://discord.com/users/1563034001378382005", "asset": "discord.svg"},
    {"id": "clubhouse", "fa": "کلاب‌هاوس", "en": "Clubhouse",
     "handle": "@voidfeedmedia", "display": None,
     "url": "https://www.clubhouse.com/@voidfeedmedia?utm_medium=ch_profile&utm_campaign=9dhHUVoP4NQBXQxtaLVpLA-2578799&chs=ARbhbkYzvK%3AEqafWzmDGjZArpuy1eYqEpnHoSPMSTFyAza1I2k_Lhk",
     "asset": "clubhouse.svg"},
]
PLATFORM_IDS = {p["id"] for p in PLATFORMS}

# Best-effort, truthful verification cache. Only Telegram is checked for real
# (Bot API getChat); every other external platform blocks anonymous validation,
# so those links stay "unverified" — never a false green checkmark.
_TG_VERIFY_CACHE: dict = {}
_TG_VERIFY_TTL = 3600


def _tg_verify_handle(handle: str) -> bool:
    handle = handle.strip()
    if not handle:
        return False
    token = _bot_token()
    if not token:
        return False
    hit = _TG_VERIFY_CACHE.get(handle)
    if hit and time.time() - hit[1] < _TG_VERIFY_TTL:
        return hit[0]
    ok = False
    try:
        r = httpx.post(
            f"{TELEGRAM_API}/bot{token}/getChat",
            json={"chat_id": handle}, timeout=8, trust_env=False,
        )
        if r.status_code == 200:
            typ = (r.json().get("result") or {}).get("type")
            ok = typ in ("channel", "supergroup", "group", "private")
    except Exception:
        ok = False
    _TG_VERIFY_CACHE[handle] = (ok, time.time())
    return ok


def _social_status(item) -> str:
    if not item.get("url"):
        return "none"
    if item.get("id") == "telegram":
        return "verified" if _tg_verify_handle(item.get("handle") or "") else "unverified"
    return "unverified"


def _platform_item(p, overrides):
    item = dict(p)
    ov = overrides.get(p["id"], {})
    item["handle"] = ov.get("handle", p.get("handle"))
    item["display"] = ov.get("display", p.get("display"))
    item["url"] = ov.get("url", p.get("url"))
    item["status"] = _social_status(item)
    item["verified"] = item["status"] == "verified"
    item["profile_type"] = p.get("profile_type", "profile")
    asset = p.get("asset")
    item["logo"] = f"/static-assets/icons/platforms/{asset}" if asset else None
    item["logo_light"] = (f"/static-assets/icons/platforms/{p['asset_light']}"
                           if p.get("asset_light") else item["logo"])
    item["logo_dark"] = (f"/static-assets/icons/platforms/{p['asset_dark']}"
                         if p.get("asset_dark") else item["logo"])
    item["logo_pending"] = p.get("asset_pending", None)
    item["logo_note"] = p.get("asset_note", None)
    return item


def _social_overrides():
    out = {}
    for p in PLATFORMS:
        url = db.get_setting(f"social_url_{p['id']}", "")
        handle = db.get_setting(f"social_handle_{p['id']}", "")
        display = db.get_setting(f"social_display_{p['id']}", "")
        if url or handle or display:
            out[p["id"]] = {"url": url or None, "handle": handle or None, "display": display or None}
    return out


@app.get("/api/profile")
def api_profile(authorization: str | None = Header(None)):
    require_admin(authorization)
    return {
        "brand": BRAND,
        "desc_fa": db.get_setting("brand_desc_fa", BRAND_DESC_FA_DEFAULT),
        "desc_en": db.get_setting("brand_desc_en", BRAND_DESC_EN_DEFAULT),
        "social": [_platform_item(p, _social_overrides()) for p in PLATFORMS],
    }


@app.put("/api/profile")
def api_profile_put(authorization: str | None = Header(None),
                     payload: dict = Body(default={})):
    require_admin(authorization)
    if "brand_desc_fa" in payload:
        db.set_setting("brand_desc_fa", str(payload["brand_desc_fa"])[:2000])
    if "brand_desc_en" in payload:
        db.set_setting("brand_desc_en", str(payload["brand_desc_en"])[:2000])
    social = payload.get("social")
    if isinstance(social, dict):
        for pid, ov in social.items():
            if pid not in PLATFORM_IDS:
                continue
            if not isinstance(ov, dict):
                continue
            url = str(ov.get("url", "")).strip()
            handle = str(ov.get("handle", "")).strip()
            display = str(ov.get("display", "")).strip()
            if url:
                if not (url.startswith("https://") or url.startswith("http://")):
                    raise HTTPException(400, f"url نامعتبر برای {pid}")
                db.set_setting(f"social_url_{pid}", url[:300])
            else:
                db.set_setting(f"social_url_{pid}", "")
            db.set_setting(f"social_handle_{pid}", handle[:120])
            db.set_setting(f"social_display_{pid}", display[:120])
    return api_profile(authorization)


@app.get("/api/connections/spec")
def api_connections_spec(authorization: str | None = Header(None)):
    require_admin(authorization)
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    out = []
    for p in PLATFORMS:
        item = _platform_item(p, _social_overrides())
        item["social_profile"] = {
            "exists": True,
            "handle": item["handle"],
            "display": item["display"],
            "url": item["url"],
            "status": item["status"],
            "verified": item["verified"],
            "profile_type": item["profile_type"],
        }
        if p["id"] == "telegram":
            item["technical"] = {
                "status": "setup_ready" if token else "setup_required",
                "kind": "bot_api",
                "capabilities": ["publish_via_bot"] if token else [],
                "note_key": "conn_telegram_note",
                "guidance": "telegram",
                "has_bot_token": bool(token),
            }
        else:
            item["technical"] = {
                "status": "not_implemented",
                "kind": "public_profile_only",
                "capabilities": [],
                "note_key": "conn_unsupported_note",
                "guidance": p["id"],
            }
        item.pop("url_verified", None)
        out.append(item)
    return out


# =====================================================================
# Multi-network Connection Center (provider-based, OAuth2 foundations)
# =====================================================================
# - Real OAuth flows are implemented only where env credentials exist.
# - Providers without credentials report status "awaiting_setup" and the
#   exact env vars that must be configured; we never simulate success.
# - Tokens are stored server-side only, encrypted at rest; raw tokens are
#   never logged and never returned to the browser.
# - State is validated per OAuth2 best practice (one-time, expiring) to
#   mitigate CSRF on the callback.
# =====================================================================

def _conn_encryption_key() -> bytes:
    key = os.environ.get("STUDIO_TOKEN_ENCRYPTION_KEY", "").strip()
    if not key:
        raise HTTPException(503, "STUDIO_TOKEN_ENCRYPTION_KEY is not set: cannot securely store tokens")
    # accept hex (64 chars = 32 bytes) or raw passphrase -> derive sha256
    if re.fullmatch(r"[0-9a-fA-F]{64}", key):
        return bytes.fromhex(key)
    return hashlib.sha256(key.encode()).digest()


def _conn_encrypt(plain: str) -> str:
    import base64
    from cryptography.fernet import Fernet
    f = Fernet(base64.urlsafe_b64encode(_conn_encryption_key()))
    return f.encrypt(plain.encode()).decode()


def _conn_decrypt(blob: str) -> str:
    import base64
    from cryptography.fernet import Fernet
    f = Fernet(base64.urlsafe_b64encode(_conn_encryption_key()))
    return f.decrypt(blob.encode()).decode()


def _oauth_state_key(provider: str) -> str:
    return f"oauth_state:{provider}"


@app.get("/api/connections")
def api_connections(authorization: str | None = Header(None)):
    require_admin(authorization)
    import providers
    out = []
    for key, spec in providers.PROVIDERS.items():
        st = providers.provider_status(key)
        conns = [dict(r) for r in db.list_connections(key)]
        # strip anything token-like before returning to the browser
        for c in conns:
            c.pop("token_encrypted", None)
            c.pop("refresh_token_encrypted", None)
        st["connections"] = conns
        if key == "telegram":
            st["connections"] = [dict(r) for r in db.list_channels()]
            st["connection_label"] = "کانال‌های متصل"
        out.append(st)
    return out


@app.post("/api/connections/{provider}/authorize")
async def api_connection_authorize(provider: str,
                                   authorization: str | None = Header(None)):
    require_admin(authorization)
    import providers
    spec = providers.get_spec(provider)
    if not spec:
        raise HTTPException(404, "Provider not found")
    if spec.auth_type == "bot":
        raise HTTPException(400, "Telegram connects through the bot; no OAuth needed")
    st = providers.provider_status(provider)
    if st["status"] != "configured":
        raise HTTPException(status_code=409, detail={
            "missing_env": st["missing_env"],
            "msg": "این شبکه هنوز پیکربندی نشده است. متغیرهای زیر لازم است: " + ", ".join(st["missing_env"]),
        })

    state = secrets.token_urlsafe(32)
    # one-time, 10-minute expiry — CSRF/state protection
    db.set_setting(_oauth_state_key(provider), json.dumps({
        "state": state, "exp": int(time.time()) + 600,
    }))

    redirect_uri = os.environ.get(f"{provider.upper()}_REDIRECT_URI", "").strip()
    if not redirect_uri:
        raise HTTPException(status_code=409, detail={
            "missing_env": [f"{provider.upper()}_REDIRECT_URI"],
        })

    params = {
        "client_id": os.environ.get(spec.client_id_env or "", "").strip(),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(spec.scopes),
        "state": state,
    }
    url = spec.oauth_authorize_url + "?" + urllib.parse.urlencode(params)
    return {"authorize_url": url, "provider": provider}


@app.get("/api/connections/{provider}/callback")
async def api_connection_callback(provider: str, code: str = "",
                                  state: str = "",
                                  error: str | None = None,
                                  error_description: str | None = None):
    if error:
        raise HTTPException(400, f"OAuth error: {error}")
    import providers
    spec = providers.get_spec(provider)
    if not spec:
        raise HTTPException(404, "Provider not found")

    # state validation (CSRF / replay protection)
    raw = db.get_setting(_oauth_state_key(provider), "")
    if not raw:
        raise HTTPException(400, "Missing or expired OAuth state")
    try:
        saved = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(400, "Invalid OAuth state")
    if saved.get("state") != state:
        raise HTTPException(400, "OAuth state mismatch")
    if int(saved.get("exp", 0)) < int(time.time()):
        db.set_setting(_oauth_state_key(provider), "")
        raise HTTPException(400, "OAuth state expired")
    db.set_setting(_oauth_state_key(provider), "")  # single-use

    # exchange code for token (server-side only)
    redirect_uri = os.environ.get(f"{provider.upper()}_REDIRECT_URI", "").strip()
    token_url = spec.oauth_token_url
    payload = {
        "client_id": os.environ.get(spec.client_id_env or "", "").strip(),
        "client_secret": os.environ.get(spec.client_secret_env or "", "").strip(),
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    try:
        async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
            r = await client.post(token_url, data=payload)
            data = r.json()
    except Exception as exc:
        logger.warning("connection token exchange failed for %s: %s", provider, type(exc).__name__)
        raise HTTPException(502, "Token exchange failed")

    access = data.get("access_token")
    if not access:
        raise HTTPException(502, "No access_token returned by provider")

    # account identity lookup (provider-specific, intentionally minimal + safe)
    account_id = str(data.get("account_id", ""))
    account_name = str(data.get("account_name", ""))
    expires_in = data.get("expires_in")
    if provider in ("instagram", "facebook"):
        user_id = data.get("user_id") or data.get("account_id") or access[-6:]
        account_id = account_id or str(user_id)
        account_name = account_name or f"{spec.label} account ({access[-4:]})"
    elif provider == "youtube":
        account_id = account_id or access[-8:]
        account_name = account_name or f"{spec.label} account"
    elif provider == "x":
        account_id = account_id or access[-8:]
        account_name = account_name or f"{spec.label} account"
    elif provider == "tiktok":
        account_id = account_id or access[-8:]
        account_name = account_name or f"{spec.label} account"

    try:
        enc_access = _conn_encrypt(access)
        enc_refresh = _conn_encrypt(data["refresh_token"]) if data.get("refresh_token") else ""
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "Token encryption unavailable")

    conn_id = db.save_connection(
        provider, account_id=account_id, account_name=account_name,
        token_encrypted=enc_access, refresh_token_encrypted=enc_refresh,
        status="connected", last_verified_at=db.utc_now(),
    )
    logger.info("connection %s saved id=%s (no tokens logged)", provider, conn_id)
    return {"ok": True, "connection_id": conn_id, "provider": provider,
            "account_name": account_name}


@app.post("/api/connections/{conn_id}/disconnect")
def api_connection_disconnect(conn_id: int,
                              authorization: str | None = Header(None)):
    require_admin(authorization)
    row = db.get_connection(conn_id)
    if not row:
        raise HTTPException(404, "Connection not found")
    db.delete_connection(conn_id)
    logger.info("connection %s (provider=%s) disconnected", conn_id, row["provider"])
    return {"ok": True, "disconnected": conn_id}


def main() -> None:
    import uvicorn
    db.init_database()
    port = int(os.environ.get("STUDIO_PORT", "8077"))
    logger.info("VoidFeed Studio listening on 127.0.0.1:%s (demo=%s)", port, DEMO)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
