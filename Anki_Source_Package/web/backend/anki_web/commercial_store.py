from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


WEB_DB_ENV = "ANKI_OCCLUSION_WEB_DB"
WEB_USER_ENV = "ANKI_OCCLUSION_WEB_USER"
DEFAULT_USER_ID = "dev-user"
DEFAULT_USER_EMAIL = "dev@example.local"

SYNCABLE_COLLECTIONS = {"decks", "cards", "masks", "review_state"}


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def default_db_path() -> Path:
    return Path(
        os.environ.get(WEB_DB_ENV)
        or Path(__file__).resolve().parents[1] / ".data" / "anki_web.sqlite3"
    )


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def json_loads(value: str | None) -> Any:
    if not value:
        return {}
    return json.loads(value)


class CommercialWebStore:
    """SQLite foundation for the paid browser app.

    This store intentionally handles metadata only. PDFs and large images stay
    browser-local for the first commercial MVP.
    """
    _initialized_db_paths = set()
    _init_lock = threading.Lock()

    def __init__(self, db_path: str | os.PathLike[str] | None = None):
        self.db_path = Path(db_path) if db_path is not None else default_db_path()
        resolved_path = str(self.db_path.resolve())
        with CommercialWebStore._init_lock:
            if resolved_path not in CommercialWebStore._initialized_db_paths:
                self.init_db()
                CommercialWebStore._initialized_db_paths.add(resolved_path)

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def connection(self):
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_db(self) -> None:
        with self.connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL,
                    plan TEXT NOT NULL DEFAULT 'dev',
                    entitled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sync_items (
                    user_id TEXT NOT NULL,
                    collection TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    deleted INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, collection, item_id)
                );

                CREATE TABLE IF NOT EXISTS sync_log (
                    revision INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    collection TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    deleted INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS request_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    method TEXT NOT NULL,
                    path TEXT NOT NULL,
                    status_code INTEGER NOT NULL,
                    duration_ms REAL NOT NULL,
                    request_bytes INTEGER NOT NULL DEFAULT 0,
                    response_bytes INTEGER NOT NULL DEFAULT 0,
                    db_reads INTEGER NOT NULL DEFAULT 0,
                    db_writes INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS client_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    event TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_sync_log_user_revision
                    ON sync_log (user_id, revision);
                CREATE INDEX IF NOT EXISTS idx_request_metrics_user_created
                    ON request_metrics (user_id, created_at);
                """
            )

    def ensure_dev_user(self, user_id: str | None = None) -> dict[str, Any]:
        resolved_user_id = user_id or os.environ.get(WEB_USER_ENV) or DEFAULT_USER_ID
        with self.connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO users (user_id, email, plan, entitled, created_at)
                VALUES (?, ?, 'dev', 1, ?)
                """,
                (resolved_user_id, DEFAULT_USER_EMAIL, utc_now()),
            )
            row = conn.execute(
                """
                SELECT user_id, email, plan, entitled
                FROM users
                WHERE user_id = ?
                """,
                (resolved_user_id,),
            ).fetchone()
        return row_to_user(row)

    def max_revision(self, user_id: str) -> int:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(revision), 0) AS revision FROM sync_log WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return int(row["revision"])

    def pull_changes(self, user_id: str, since_revision: int = 0) -> dict[str, Any]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT revision, collection, item_id, deleted, payload_json
                FROM sync_log
                WHERE user_id = ? AND revision > ?
                ORDER BY revision ASC
                """,
                (user_id, int(since_revision)),
            ).fetchall()
            changes = [row_to_change(row) for row in rows]
            if changes:
                revision = changes[-1]["revision"]
            else:
                max_row = conn.execute(
                    "SELECT COALESCE(MAX(revision), 0) AS revision FROM sync_log WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
                revision = int(max_row["revision"])
        return {"revision": revision, "changes": changes}

    def push_changes(self, user_id: str, changes: list[Any]) -> dict[str, Any]:
        accepted = 0
        with self.connection() as conn:
            max_row = conn.execute(
                "SELECT COALESCE(MAX(revision), 0) AS revision FROM sync_log WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            latest_revision = int(max_row["revision"])
            
            for change in changes:
                normalized = normalize_change(change)
                
                # Check for idempotency: does the new change match what's already stored in sync_items?
                row = conn.execute(
                    """
                    SELECT deleted, payload_json FROM sync_items
                    WHERE user_id = ? AND collection = ? AND item_id = ?
                    """,
                    (user_id, normalized["collection"], normalized["item_id"])
                ).fetchone()
                
                if row is not None:
                    stored_deleted = bool(row["deleted"])
                    stored_payload = json_loads(row["payload_json"])
                    if stored_deleted == normalized["deleted"] and stored_payload == normalized["payload"]:
                        # Identical change, bypass sync_log and sync_items insert
                        accepted += 1
                        continue

                now = utc_now()
                cur = conn.execute(
                    """
                    INSERT INTO sync_log (
                        user_id, collection, item_id, deleted, payload_json, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        normalized["collection"],
                        normalized["item_id"],
                        int(normalized["deleted"]),
                        json_dumps(normalized["payload"]),
                        now,
                    ),
                )
                latest_revision = int(cur.lastrowid)
                conn.execute(
                    """
                    INSERT INTO sync_items (
                        user_id, collection, item_id, revision, deleted, payload_json, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, collection, item_id) DO UPDATE SET
                        revision = excluded.revision,
                        deleted = excluded.deleted,
                        payload_json = excluded.payload_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        user_id,
                        normalized["collection"],
                        normalized["item_id"],
                        latest_revision,
                        int(normalized["deleted"]),
                        json_dumps(normalized["payload"]),
                        now,
                    ),
                )
                accepted += 1
        return {"accepted": accepted, "revision": latest_revision, "conflicts": []}

    def record_client_metric(
        self, user_id: str, event: str, payload: dict[str, Any] | None = None
    ) -> dict[str, bool]:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO client_metrics (user_id, event, payload_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, event, json_dumps(payload or {}), utc_now()),
            )
        return {"recorded": True}

    def record_request_metric(
        self,
        *,
        user_id: str,
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
        request_bytes: int = 0,
        response_bytes: int = 0,
        db_reads: int = 0,
        db_writes: int = 0,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO request_metrics (
                    user_id, method, path, status_code, duration_ms,
                    request_bytes, response_bytes, db_reads, db_writes, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    method,
                    path,
                    int(status_code),
                    float(duration_ms),
                    int(request_bytes),
                    int(response_bytes),
                    int(db_reads),
                    int(db_writes),
                    utc_now(),
                ),
            )

    def cost_snapshot(self, user_id: str | None = None) -> dict[str, Any]:
        where = "WHERE user_id = ?" if user_id else ""
        params = (user_id,) if user_id else ()
        with self.connection() as conn:
            totals = conn.execute(
                f"""
                SELECT
                    COUNT(*) AS request_count,
                    COALESCE(SUM(request_bytes), 0) AS request_bytes,
                    COALESCE(SUM(response_bytes), 0) AS response_bytes,
                    COALESCE(AVG(duration_ms), 0) AS avg_duration_ms,
                    COALESCE(SUM(db_reads), 0) AS db_reads,
                    COALESCE(SUM(db_writes), 0) AS db_writes
                FROM request_metrics
                {where}
                """,
                params,
            ).fetchone()
            slow_rows = conn.execute(
                f"""
                SELECT method, path, status_code, duration_ms, created_at
                FROM request_metrics
                {where}
                ORDER BY duration_ms DESC
                LIMIT 5
                """,
                params,
            ).fetchall()
            sync_changes = conn.execute(
                f"SELECT COUNT(*) AS count FROM sync_log {where}",
                params,
            ).fetchone()
        storage_bytes = self.db_path.stat().st_size if self.db_path.exists() else 0
        return {
            "request_count": int(totals["request_count"]),
            "request_bytes": int(totals["request_bytes"]),
            "response_bytes": int(totals["response_bytes"]),
            "avg_duration_ms": round(float(totals["avg_duration_ms"]), 3),
            "db_reads": int(totals["db_reads"]),
            "db_writes": int(totals["db_writes"]),
            "sync_changes": int(sync_changes["count"]),
            "storage_bytes": int(storage_bytes),
            "slow_routes": [dict(row) for row in slow_rows],
        }


def normalize_change(change: Any) -> dict[str, Any]:
    collection = str(change_value(change, "collection", ""))
    item_id = str(change_value(change, "item_id", ""))
    payload = change_value(change, "payload", {})
    deleted = bool(change_value(change, "deleted", False))

    if collection not in SYNCABLE_COLLECTIONS:
        raise ValueError(f"collection must be one of {sorted(SYNCABLE_COLLECTIONS)}")
    if not item_id:
        raise ValueError("item_id is required")
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")

    return {
        "collection": collection,
        "item_id": item_id,
        "payload": payload,
        "deleted": deleted,
    }


def change_value(change: Any, key: str, default: Any = None) -> Any:
    if isinstance(change, dict):
        return change.get(key, default)
    return getattr(change, key, default)


def estimate_request_db_units(method: str, path: str) -> tuple[int, int]:
    method = method.upper()
    reads = 0
    writes = 1  # request metric row
    if path == "/api/me":
        reads += 1
    elif path.startswith("/api/sync/pull"):
        reads += 2
    elif path.startswith("/api/sync/push"):
        writes += 2
    elif path.startswith("/api/metrics/client"):
        writes += 1
    elif path.startswith("/api/metrics/cost"):
        reads += 3
    elif path.startswith("/api/"):
        reads += 1 if method == "GET" else 0
        writes += 1 if method in {"POST", "PUT", "PATCH", "DELETE"} else 0
    return reads, writes


def row_to_user(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "user_id": row["user_id"],
        "email": row["email"],
        "plan": row["plan"],
        "entitled": bool(row["entitled"]),
    }


def row_to_change(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "revision": int(row["revision"]),
        "collection": row["collection"],
        "item_id": row["item_id"],
        "payload": json_loads(row["payload_json"]),
        "deleted": bool(row["deleted"]),
    }
