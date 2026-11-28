"""Shared test fixture: order-independent WORK_DIR/DB_PATH isolation.

Root cause: unittest imports every test module before running any test, so a
per-module import-time bind only reflects the LAST module imported. All suites
would then share that final module's DB.

Two helpers:
- `prepare_workspace(tag)`: idempotent per tag; re-pins the DB to this
  module's dir. Call it again in setUpClass so each class runs against its own
  DB regardless of import order.
- `reset_workspace(tag)`: always makes a brand-new dir (fresh DB). Use in
  setUp when a test needs a clean database regardless of prior tests.

`_bind` only re-executes voidfeed_db when the target dir differs from the
currently bound one — repeated binds to the same dir are no-ops, which avoids
file-descriptor churn from many importlib.reload cycles.
"""
import importlib
import os
import sys
import tempfile
from pathlib import Path

_DIRS: dict[str, Path] = {}


def _bound_to(d: Path) -> bool:
    mod = sys.modules.get("voidfeed_db")
    return bool(mod and str(getattr(mod, "DB_PATH", "")).startswith(str(d)))


def _bind(d: Path) -> Path:
    os.environ["WORK_DIR"] = str(d)
    if _bound_to(d):
        return d
    mod = sys.modules.get("voidfeed_db")
    if mod is None:
        import voidfeed_db as mod
    importlib.reload(mod)
    if hasattr(mod, "init_database"):
        mod.init_database()
    return d


def prepare_workspace(tag: str) -> Path:
    d = _DIRS.get(tag)
    if d is None:
        d = Path(tempfile.mkdtemp(prefix=f"vfb_{tag}_"))
        _DIRS[tag] = d
    return _bind(d)


def reset_workspace(tag: str) -> Path:
    d = Path(tempfile.mkdtemp(prefix=f"vfb_{tag}_"))
    return _bind(d)


def clear_data() -> None:
    """Wipe all data rows (keeps the schema) in the currently-bound DB."""
    import voidfeed_db as mod
    with mod.get_db() as conn:
        for t in ("drafts", "media_library", "templates", "connections",
                  "publish_history", "news_seen", "channels"):
            try:
                conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
