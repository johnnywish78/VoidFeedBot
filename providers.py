"""Multi-network provider registry for VoidFeed Studio.

Architecture:
- Each provider declares its configuration, auth type, scopes, publishing
  capability, and required environment variables.
- No tokens or secrets are stored in this module. Tokens live server-side
  only, encrypted at rest (see studio.py connection storage).
- A provider is "awaiting_setup" until all its required env vars are set.
  Without credentials we never simulate a connected state.

Providers implemented:
  telegram   — existing bot-based integration (channels table)
  instagram  — Meta OAuth (pending creds)
  facebook   — Meta OAuth (pending creds)
  youtube    — Google OAuth (pending creds)
  x         — X OAuth (pending creds)
  tiktok    — TikTok Login Kit (pending creds)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class ProviderSpec:
    key: str
    label: str
    brand_color: str
    auth_type: str                      # "bot" | "oauth2"
    needs_client_id: bool
    needs_client_secret: bool
    client_id_env: Optional[str] = None
    client_secret_env: Optional[str] = None
    oauth_authorize_url: Optional[str] = None
    oauth_token_url: Optional[str] = None
    scopes: tuple = field(default_factory=tuple)
    publish_available: bool = False     # can we publish (real) today?
    docs_url: str = ""
    required_permissions: tuple = field(default_factory=tuple)


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _mask(v: str, n: int = 4) -> str:
    if not v:
        return ""
    return v[-n:] if len(v) <= n else "*" * (len(v) - n) + v[-n:]


PROVIDERS: dict[str, ProviderSpec] = {
    "telegram": ProviderSpec(
        key="telegram", label="Telegram", brand_color="#2AABEE",
        auth_type="bot", needs_client_id=False, needs_client_secret=False,
        publish_available=True,
        docs_url="https://core.telegram.org/bots/api",
    ),
    "instagram": ProviderSpec(
        key="instagram", label="Instagram", brand_color="#E4405F",
        auth_type="oauth2", needs_client_id=True, needs_client_secret=True,
        client_id_env="INSTAGRAM_CLIENT_ID", client_secret_env="INSTAGRAM_CLIENT_SECRET",
        oauth_authorize_url="https://www.facebook.com/v19.0/dialog/oauth",
        oauth_token_url="https://graph.facebook.com/v19.0/oauth/access_token",
        scopes=("instagram_basic", "instagram_content_publish"),
        publish_available=False,
        docs_url="https://developers.facebook.com/docs/instagram-platform",
        required_permissions=("instagram_basic", "instagram_content_publish"),
    ),
    "facebook": ProviderSpec(
        key="facebook", label="Facebook", brand_color="#1877F2",
        auth_type="oauth2", needs_client_id=True, needs_client_secret=True,
        client_id_env="FACEBOOK_APP_ID", client_secret_env="FACEBOOK_APP_SECRET",
        oauth_authorize_url="https://www.facebook.com/v19.0/dialog/oauth",
        oauth_token_url="https://graph.facebook.com/v19.0/oauth/access_token",
        scopes=("pages_show_list", "pages_manage_posts"),
        publish_available=False,
        docs_url="https://developers.facebook.com/docs/pages-api",
        required_permissions=("pages_show_list", "pages_manage_posts"),
    ),
    "youtube": ProviderSpec(
        key="youtube", label="YouTube", brand_color="#FF0000",
        auth_type="oauth2", needs_client_id=True, needs_client_secret=True,
        client_id_env="YOUTUBE_CLIENT_ID", client_secret_env="YOUTUBE_CLIENT_SECRET",
        oauth_authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        oauth_token_url="https://oauth2.googleapis.com/token",
        scopes=("https://www.googleapis.com/auth/youtube.upload",),
        publish_available=False,
        docs_url="https://developers.google.com/youtube/v3",
        required_permissions=("youtube.upload",),
    ),
    "x": ProviderSpec(
        key="x", label="X (Twitter)", brand_color="#000000",
        auth_type="oauth2", needs_client_id=True, needs_client_secret=True,
        client_id_env="X_CLIENT_ID", client_secret_env="X_CLIENT_SECRET",
        oauth_authorize_url="https://twitter.com/i/oauth2/authorize",
        oauth_token_url="https://api.x.com/2/oauth2/token",
        scopes=("tweet.read", "tweet.write", "users.read", "offline.access"),
        publish_available=False,
        docs_url="https://developer.x.com/en/docs/authentication/oauth-2-0",
        required_permissions=("tweet.read", "tweet.write"),
    ),
    "tiktok": ProviderSpec(
        key="tiktok", label="TikTok", brand_color="#000000",
        auth_type="oauth2", needs_client_id=True, needs_client_secret=True,
        client_id_env="TIKTOK_CLIENT_KEY", client_secret_env="TIKTOK_CLIENT_SECRET",
        oauth_authorize_url="https://www.tiktok.com/v2/auth/authorize",
        oauth_token_url="https://open.tiktokapis.com/v2/oauth/token/",
        scopes=("user.info.basic", "video.publish"),
        publish_available=False,
        docs_url="https://developers.tiktok.com/doc/login-kit-web",
        required_permissions=("user.info.basic", "video.publish"),
    ),
}


def provider_status(key: str) -> dict:
    """Return a truthful status view for a provider. Never exposes secrets."""
    spec = PROVIDERS.get(key)
    if not spec:
        return {"key": key, "status": "unknown", "label": key}

    if spec.auth_type == "bot":
        # Telegram: configured iff bot token is present. Connected accounts are
        # the registered channels (queried by the caller).
        bot_token = _env("TELEGRAM_BOT_TOKEN")
        return {
            "key": key,
            "label": spec.label,
            "auth_type": "bot",
            "status": "configured" if bot_token else "awaiting_setup",
            "missing_env": [] if bot_token else ["TELEGRAM_BOT_TOKEN"],
            "publish_available": spec.publish_available,
            "docs_url": spec.docs_url,
        }

    missing = []
    if spec.needs_client_id and not _env(spec.client_id_env or ""):
        missing.append(spec.client_id_env or "")
    if spec.needs_client_secret and not _env(spec.client_secret_env or ""):
        missing.append(spec.client_secret_env or "")

    return {
        "key": key,
        "label": spec.label,
        "auth_type": spec.auth_type,
        "status": "awaiting_setup" if missing else "configured",
        "missing_env": missing,
        "scopes": list(spec.scopes),
        "required_permissions": list(spec.required_permissions),
        "publish_available": spec.publish_available,
        "docs_url": spec.docs_url,
        "brand_color": spec.brand_color,
    }


def get_spec(key: str) -> Optional[ProviderSpec]:
    return PROVIDERS.get(key)
