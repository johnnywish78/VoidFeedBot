"""Shared SQLite layer for VoidFeedBot (bot.py + studio.py).

Live DB: data/voidfeed.sqlite3 — additive/rebuild migrations only,
existing rows are preserved.
"""
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(os.environ.get("WORK_DIR", Path(__file__).resolve().parent))
DATA_DIR = Path(BASE_DIR) / "data"
DB_PATH = DATA_DIR / "voidfeed.sqlite3"
MEDIA_DIR = DATA_DIR / "media"

STATUSES = ("draft", "approved", "rejected", "scheduled", "published", "publish_failed")
QUEUE_LIMIT = 10


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class _ClosingConnection(sqlite3.Connection):
    """sqlite3.Connection whose `with` block also closes the connection.

    The stock sqlite3 context manager only commits/rolls back; the connection
    is left to the garbage collector, which exhausts file descriptors under
    heavy test load. Closing on __exit__ makes every `with get_db()` leak-free.
    """

    def __exit__(self, *exc):
        try:
            return super().__exit__(*exc)
        finally:
            self.close()


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10, factory=_ClosingConnection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_database() -> None:
    DATA_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(DATA_DIR, 0o700)
    MEDIA_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)

    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft', 'approved', 'rejected')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                reviewed_at TEXT,
                reviewed_by INTEGER
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_drafts_status_id
            ON drafts(status, id DESC)
        """)

    migrate()
    os.chmod(DB_PATH, 0o600)


def migrate() -> None:
    """Rebuild drafts to the extended schema; create channels/templates/settings."""
    with get_db() as conn:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(drafts)")]
        if "scheduled_at" not in cols:
            conn.execute("BEGIN")
            conn.execute("""
                CREATE TABLE drafts_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft'
                        CHECK (status IN ('draft', 'approved', 'rejected',
                                          'scheduled', 'published', 'publish_failed')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    reviewed_at TEXT,
                    reviewed_by INTEGER,
                    channel_id INTEGER,
                    media_path TEXT,
                    media_kind TEXT,
                    scheduled_at TEXT,
                    published_at TEXT,
                    publish_error TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    source TEXT NOT NULL DEFAULT 'bot',
                    ai_meta TEXT
                )
            """)
            conn.execute("""
                INSERT INTO drafts_new
                    (id, content, status, created_at, updated_at,
                     reviewed_at, reviewed_by)
                SELECT id, content, status, created_at, updated_at,
                       reviewed_at, reviewed_by
                FROM drafts
            """)
            conn.execute("DROP TABLE drafts")
            conn.execute("ALTER TABLE drafts_new RENAME TO drafts")
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_drafts_status_id
                ON drafts(status, id DESC)
            """)
            conn.execute("COMMIT")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER UNIQUE NOT NULL,
                title TEXT NOT NULL,
                username TEXT,
                is_default INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                body TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS connections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                account_id TEXT,
                account_name TEXT,
                account_type TEXT,
                token_encrypted TEXT,
                refresh_token_encrypted TEXT,
                token_expires_at TEXT,
                status TEXT NOT NULL DEFAULT 'configured',
                last_verified_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(provider, account_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS publish_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                draft_id INTEGER,
                channel_id INTEGER,
                triggered_by TEXT NOT NULL DEFAULT 'studio',
                event TEXT NOT NULL,
                details TEXT,
                scheduled_at TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS media_library (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL UNIQUE,
                original_name TEXT,
                kind TEXT NOT NULL DEFAULT 'photo',
                size_bytes INTEGER NOT NULL DEFAULT 0,
                mime TEXT,
                alt_text TEXT NOT NULL DEFAULT '',
                caption TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_history_created
            ON publish_history(created_at DESC)
        """)
        # v3: chat kind + per-network variants + editable wordlists
        dcols = [r["name"] for r in conn.execute("PRAGMA table_info(drafts)")]
        if "variants" not in dcols:
            conn.execute("ALTER TABLE drafts ADD COLUMN variants TEXT")
        ccols = [r["name"] for r in conn.execute("PRAGMA table_info(channels)")]
        if "kind" not in ccols:
            conn.execute("ALTER TABLE channels ADD COLUMN kind TEXT NOT NULL DEFAULT 'channel'")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mod_words (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                term TEXT NOT NULL,
                is_regex INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE(category, term)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mod_users (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT,
                first_name TEXT,
                warnings INTEGER NOT NULL DEFAULT 0,
                total_strikes INTEGER NOT NULL DEFAULT 0,
                banned_until TEXT,
                banned_forever INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT,
                created_at TEXT NOT NULL,
                PRIMARY KEY (chat_id, user_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mod_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER,
                action TEXT NOT NULL,
                reason TEXT,
                detail TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS news_seen (
                link_hash TEXT PRIMARY KEY,
                source TEXT,
                title TEXT,
                created_at TEXT NOT NULL
            )
        """)


# ---------------- drafts ----------------

def save_draft(content: str, *, channel_id=None, media_path=None,
               media_kind=None, source="bot", status="draft") -> int:
    now = utc_now()
    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO drafts (content, status, created_at, updated_at,
                                channel_id, media_path, media_kind, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (content, status, now, now, channel_id, media_path, media_kind, source),
        )
        return int(cur.lastrowid)


def list_drafts(status=None, limit=200) -> list[sqlite3.Row]:
    q = ("SELECT * FROM drafts WHERE status = ? ORDER BY id DESC LIMIT ?"
         if status else "SELECT * FROM drafts ORDER BY id DESC LIMIT ?")
    args = (status, limit) if status else (limit,)
    with get_db() as conn:
        return conn.execute(q, args).fetchall()


def get_draft(draft_id: int) -> sqlite3.Row | None:
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM drafts WHERE id = ?", (draft_id,)
        ).fetchone()


def update_draft(draft_id: int, **fields) -> bool:
    if not fields:
        return False
    fields["updated_at"] = utc_now()
    sets = ", ".join(f"{k} = ?" for k in fields)
    with get_db() as conn:
        cur = conn.execute(
            f"UPDATE drafts SET {sets} WHERE id = ?",
            (*fields.values(), draft_id),
        )
        return cur.rowcount > 0


def set_draft_status(draft_id: int, status: str, *, admin_id=None,
                     scheduled_at=None) -> str:
    now = utc_now()
    with get_db() as conn:
        row = conn.execute(
            "SELECT status FROM drafts WHERE id = ?", (draft_id,)
        ).fetchone()
        if row is None:
            return "not_found"
        conn.execute(
            """
            UPDATE drafts SET status = ?, updated_at = ?, reviewed_at = ?,
                              reviewed_by = ?, scheduled_at = ?,
                              publish_error = NULL, attempts = 0
            WHERE id = ?
            """,
            (status, now, now, admin_id, scheduled_at, draft_id),
        )
    return "updated"


def delete_draft(draft_id: int) -> bool:
    with get_db() as conn:
        cur = conn.execute("DELETE FROM drafts WHERE id = ?", (draft_id,))
        return cur.rowcount > 0


def due_scheduled() -> list[sqlite3.Row]:
    with get_db() as conn:
        return conn.execute(
            """
            SELECT * FROM drafts
            WHERE status = 'scheduled'
              AND scheduled_at IS NOT NULL
              AND scheduled_at <= ?
            ORDER BY scheduled_at
            """,
            (utc_now(),),
        ).fetchall()


def stats() -> dict:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM drafts GROUP BY status"
        ).fetchall()
        counts = {r["status"]: r["n"] for r in rows}
    return {
        "draft": counts.get("draft", 0),
        "approved": counts.get("approved", 0),
        "scheduled": counts.get("scheduled", 0),
        "published": counts.get("published", 0),
        "publish_failed": counts.get("publish_failed", 0),
        "rejected": counts.get("rejected", 0),
    }


def plan_month(month_prefix: str) -> list[sqlite3.Row]:
    with get_db() as conn:
        return conn.execute(
            """
            SELECT id, content, status, scheduled_at, published_at, channel_id
            FROM drafts
            WHERE (scheduled_at LIKE ? OR published_at LIKE ?)
            ORDER BY COALESCE(scheduled_at, published_at)
            """,
            (month_prefix + "%", month_prefix + "%"),
        ).fetchall()


# ---------------- channels ----------------

def list_channels() -> list[sqlite3.Row]:
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM channels ORDER BY is_default DESC, id"
        ).fetchall()


def get_channel(channel_id: int) -> sqlite3.Row | None:
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM channels WHERE id = ?", (channel_id,)
        ).fetchone()


def add_channel(chat_id: int, title: str, username=None) -> int:
    now = utc_now()
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM channels WHERE chat_id = ?", (chat_id,)
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE channels SET title = ?, username = ?, active = 1 WHERE id = ?",
                (title, username, row["id"]),
            )
            return row["id"]
        cur = conn.execute(
            """
            INSERT INTO channels (chat_id, title, username, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (chat_id, title, username, now),
        )
        if conn.execute("SELECT COUNT(*) FROM channels").fetchone()[0] == 1:
            conn.execute(
                "UPDATE channels SET is_default = 1 WHERE id = ?", (cur.lastrowid,)
            )
        return int(cur.lastrowid)


def remove_channel(channel_id: int) -> bool:
    with get_db() as conn:
        cur = conn.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
        if cur.rowcount:
            remaining = conn.execute("SELECT COUNT(*) FROM channels").fetchone()[0]
            if remaining and not conn.execute(
                "SELECT 1 FROM channels WHERE is_default = 1"
            ).fetchone():
                first = conn.execute(
                    "SELECT id FROM channels ORDER BY id LIMIT 1"
                ).fetchone()
                conn.execute(
                    "UPDATE channels SET is_default = 1 WHERE id = ?", (first["id"],)
                )
        return cur.rowcount > 0


def set_default_channel(channel_id: int) -> bool:
    with get_db() as conn:
        if not conn.execute("SELECT 1 FROM channels WHERE id = ?", (channel_id,)).fetchone():
            return False
        conn.execute("UPDATE channels SET is_default = 0")
        conn.execute("UPDATE channels SET is_default = 1 WHERE id = ?", (channel_id,))
        return True


def register_chat(chat_id: int, title: str, username=None, kind="channel") -> int:
    """Auto-register a chat the bot is already in (channel/group/community)."""
    now = utc_now()
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM channels WHERE chat_id = ?", (chat_id,)
        ).fetchone()
        if row:
            conn.execute(
                """
                UPDATE channels SET title = ?, username = COALESCE(?, username),
                                    kind = ?, active = 1 WHERE id = ?
                """,
                (title, username, kind, row["id"]),
            )
            return row["id"]
        cur = conn.execute(
            """
            INSERT INTO channels (chat_id, title, username, kind, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (chat_id, title, username, kind, now),
        )
        if kind == "channel" and not conn.execute(
            "SELECT 1 FROM channels WHERE is_default = 1 AND kind = 'channel'"
        ).fetchone():
            conn.execute(
                "UPDATE channels SET is_default = 1 WHERE id = ?", (cur.lastrowid,)
            )
        return int(cur.lastrowid)


def get_chat_by_id(chat_id: int) -> sqlite3.Row | None:
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM channels WHERE chat_id = ?", (chat_id,)
        ).fetchone()


def get_default_channel() -> sqlite3.Row | None:
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM channels WHERE is_default = 1 ORDER BY id LIMIT 1"
        ).fetchone()


# ---------------- settings ----------------

def get_setting(key: str, default=None):
    with get_db() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value) -> None:
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )


# ---------------- connections (multi-network) ----------------

def list_connections(provider: str | None = None) -> list[sqlite3.Row]:
    with get_db() as conn:
        if provider:
            return conn.execute(
                "SELECT * FROM connections WHERE provider = ? ORDER BY id",
                (provider,),
            ).fetchall()
        return conn.execute("SELECT * FROM connections ORDER BY provider, id").fetchall()


def get_connection(conn_id: int) -> sqlite3.Row | None:
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM connections WHERE id = ?", (conn_id,)
        ).fetchone()


def save_connection(provider: str, *, account_id: str, account_name: str,
                    account_type: str = "personal",
                    token_encrypted: str = "",
                    refresh_token_encrypted: str = "",
                    token_expires_at: str | None = None,
                    status: str = "connected",
                    last_verified_at: str | None = None) -> int:
    now = utc_now()
    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO connections
                (provider, account_id, account_name, account_type,
                 token_encrypted, refresh_token_encrypted, token_expires_at,
                 status, last_verified_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(provider, account_id) DO UPDATE SET
                account_name = excluded.account_name,
                account_type = excluded.account_type,
                token_encrypted = excluded.token_encrypted,
                refresh_token_encrypted = excluded.refresh_token_encrypted,
                token_expires_at = excluded.token_expires_at,
                status = excluded.status,
                last_verified_at = excluded.last_verified_at,
                updated_at = excluded.updated_at
            """,
            (provider, account_id, account_name, account_type,
             token_encrypted, refresh_token_encrypted, token_expires_at,
             status, last_verified_at or now, now, now),
        )
        return int(cur.lastrowid) if cur.lastrowid else 0


def update_connection_status(conn_id: int, status: str,
                             last_verified_at: str | None = None) -> None:
    now = utc_now()
    with get_db() as conn:
        conn.execute(
            "UPDATE connections SET status = ?, updated_at = ?, last_verified_at = COALESCE(?, last_verified_at) WHERE id = ?",
            (status, now, last_verified_at, conn_id),
        )


def delete_connection(conn_id: int) -> bool:
    with get_db() as conn:
        cur = conn.execute("DELETE FROM connections WHERE id = ?", (conn_id,))
        return cur.rowcount > 0


# ---------------- publish history (append-only) ----------------

def add_publish_event(draft_id, channel_id, event, *, details=None,
                     scheduled_at=None, triggered_by="studio") -> int:
    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO publish_history
                (draft_id, channel_id, triggered_by, event, details,
                 scheduled_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (draft_id, channel_id, triggered_by, event, details,
             scheduled_at, utc_now()),
        )
        return int(cur.lastrowid or 0)


def list_publish_events(event: str | None = None, limit: int = 200) -> list[sqlite3.Row]:
    with get_db() as conn:
        if event:
            return conn.execute(
                "SELECT * FROM publish_history WHERE event = ? ORDER BY id DESC LIMIT ?",
                (event, min(limit, 500)),
            ).fetchall()
        return conn.execute(
            "SELECT * FROM publish_history ORDER BY id DESC LIMIT ?",
            (min(limit, 500),),
        ).fetchall()


# ---------------- media library ----------------

def add_media_item(filename: str, *, original_name: str = "", kind: str = "photo",
                   size_bytes: int = 0, mime: str = "") -> int:
    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO media_library (filename, original_name, kind, size_bytes, mime, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(filename) DO NOTHING
            """,
            (filename, original_name, kind, size_bytes, mime, utc_now()),
        )
        return int(cur.lastrowid or 0)


def list_media_items() -> list[sqlite3.Row]:
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM media_library ORDER BY id DESC"
        ).fetchall()


def get_media_item(item_id: int) -> sqlite3.Row | None:
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM media_library WHERE id = ?", (item_id,)
        ).fetchone()


def update_media_item(item_id: int, *, alt_text: str = "", caption: str = "") -> bool:
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE media_library SET alt_text = ?, caption = ? WHERE id = ?",
            (alt_text, caption, item_id),
        )
        return cur.rowcount > 0


def media_referenced(filename: str) -> bool:
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM drafts WHERE media_path IS NOT NULL AND (media_path = ? OR media_path LIKE ?) LIMIT 1",
            (filename, "%/" + filename),
        ).fetchone()
        return row is not None


def delete_media_item(item_id: int) -> bool:
    with get_db() as conn:
        cur = conn.execute("DELETE FROM media_library WHERE id = ?", (item_id,))
        return cur.rowcount > 0


# ---------------- templates ----------------

def list_templates() -> list[sqlite3.Row]:
    with get_db() as conn:
        return conn.execute("SELECT * FROM templates ORDER BY id").fetchall()


def get_template(template_id: int) -> sqlite3.Row | None:
    with get_db() as conn:
        return conn.execute("SELECT * FROM templates WHERE id = ?", (template_id,)).fetchone()


def save_template(name: str, body: str, template_id: int | None = None) -> int:
    with get_db() as conn:
        if template_id:
            conn.execute("UPDATE templates SET name = ?, body = ? WHERE id = ?",
                         (name, body, template_id))
            return template_id
        cur = conn.execute("INSERT INTO templates (name, body, created_at) VALUES (?, ?, ?)",
                           (name, body, utc_now()))
        return int(cur.lastrowid or 0)


def delete_template(template_id: int) -> bool:
    with get_db() as conn:
        cur = conn.execute("DELETE FROM templates WHERE id = ?", (template_id,))
        return cur.rowcount > 0


# ---------------- moderation ----------------

def get_mod_user(chat_id: int, user_id: int) -> sqlite3.Row | None:
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM mod_users WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        ).fetchone()


def strike_user(chat_id: int, user_id: int, *, username=None,
                first_name=None) -> sqlite3.Row:
    """Increment warnings + total_strikes; returns the fresh row."""
    now = utc_now()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO mod_users (chat_id, user_id, username, first_name,
                                   warnings, total_strikes, updated_at, created_at)
            VALUES (?, ?, ?, ?, 1, 1, ?, ?)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET
                warnings = warnings + 1,
                total_strikes = total_strikes + 1,
                username = COALESCE(excluded.username, username),
                first_name = COALESCE(excluded.first_name, first_name),
                updated_at = excluded.updated_at
            """,
            (chat_id, user_id, username, first_name, now, now),
        )
    return get_mod_user(chat_id, user_id)


def clear_warnings(chat_id: int, user_id: int) -> bool:
    with get_db() as conn:
        cur = conn.execute(
            """
            UPDATE mod_users SET warnings = 0, updated_at = ?
            WHERE chat_id = ? AND user_id = ?
            """,
            (utc_now(), chat_id, user_id),
        )
        return cur.rowcount > 0


def set_ban(chat_id: int, user_id: int, *, until=None,
            forever=False, username=None, first_name=None) -> None:
    now = utc_now()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO mod_users (chat_id, user_id, username, first_name,
                                   banned_until, banned_forever, updated_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET
                banned_until = excluded.banned_until,
                banned_forever = excluded.banned_forever,
                username = COALESCE(excluded.username, username),
                first_name = COALESCE(excluded.first_name, first_name),
                updated_at = excluded.updated_at
            """,
            (chat_id, user_id, username, first_name, until,
             1 if forever else 0, now, now),
        )


def unban_user(chat_id: int, user_id: int) -> bool:
    with get_db() as conn:
        cur = conn.execute(
            """
            UPDATE mod_users SET banned_until = NULL, banned_forever = 0,
                                  warnings = 0, updated_at = ?
            WHERE chat_id = ? AND user_id = ?
            """,
            (utc_now(), chat_id, user_id),
        )
        return cur.rowcount > 0


def is_banned(row) -> bool:
    if row is None:
        return False
    if row["banned_forever"]:
        return True
    if row["banned_until"]:
        try:
            return row["banned_until"] > utc_now()
        except TypeError:
            return False
    return False


def log_mod_action(chat_id: int, user_id, action: str,
                   reason=None, detail=None) -> None:
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO mod_log (chat_id, user_id, action, reason, detail, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (chat_id, user_id, action, reason, detail, utc_now()),
        )


def mod_stats(chat_id: int) -> dict:
    with get_db() as conn:
        warned = conn.execute(
            "SELECT COUNT(*) FROM mod_users WHERE chat_id = ? AND warnings > 0",
            (chat_id,),
        ).fetchone()[0]
        banned = conn.execute(
            "SELECT COUNT(*) FROM mod_users WHERE chat_id = ? AND (banned_forever = 1 OR banned_until > ?)",
            (chat_id, utc_now()),
        ).fetchone()[0]
        total = conn.execute(
            "SELECT COUNT(*) FROM mod_log WHERE chat_id = ?", (chat_id,)
        ).fetchone()[0]
    return {"warned": warned, "banned": banned, "actions": total}


def mod_words_all() -> list[sqlite3.Row]:
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM mod_words ORDER BY category, id"
        ).fetchall()


def mod_word_add(category: str, term: str, is_regex=False) -> bool:
    with get_db() as conn:
        try:
            conn.execute(
                """
                INSERT INTO mod_words (category, term, is_regex, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (category, term, 1 if is_regex else 0, utc_now()),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def mod_word_remove(category: str, term: str) -> bool:
    with get_db() as conn:
        cur = conn.execute(
            "DELETE FROM mod_words WHERE category = ? AND term = ?",
            (category, term),
        )
        return cur.rowcount > 0


def mod_banned_list() -> list[sqlite3.Row]:
    with get_db() as conn:
        return conn.execute(
            """
            SELECT * FROM mod_users
            WHERE banned_forever = 1 OR (banned_until IS NOT NULL AND banned_until > ?)
            ORDER BY updated_at DESC LIMIT 200
            """,
            (utc_now(),),
        ).fetchall()


def mod_log_recent(chat_id=None, limit=50) -> list[sqlite3.Row]:
    q = ("SELECT * FROM mod_log WHERE chat_id = ? ORDER BY id DESC LIMIT ?"
         if chat_id else "SELECT * FROM mod_log ORDER BY id DESC LIMIT ?")
    args = (chat_id, limit) if chat_id else (limit,)
    with get_db() as conn:
        return conn.execute(q, args).fetchall()


# ---------------- news ----------------

def news_seen_add(link_hash: str, source: str, title: str) -> bool:
    """Insert a seen news link; False if already present."""
    with get_db() as conn:
        try:
            conn.execute(
                "INSERT INTO news_seen (link_hash, source, title, created_at) VALUES (?, ?, ?, ?)",
                (link_hash, source, title[:300], utc_now()),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def news_seen_count() -> int:
    with get_db() as conn:
        return conn.execute("SELECT COUNT(*) FROM news_seen").fetchone()[0]


def news_seen_prune(keep: int = 5000) -> None:
    with get_db() as conn:
        conn.execute(
            """
            DELETE FROM news_seen WHERE rowid NOT IN (
                SELECT rowid FROM news_seen ORDER BY created_at DESC LIMIT ?
            )
            """,
            (keep,),
        )
