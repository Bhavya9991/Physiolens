"""One local SQLite file for agent runs.

Closing the browser tab does not delete a row. The server process writes
each step as it finishes. There are no accounts and no database server.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from apps.backend.paths import DATA_DIR
from apps.backend.runlog import delete_all_logs, delete_log

DB_PATH = DATA_DIR / "runs.sqlite3"
_LOCK = threading.Lock()
MAX_RUNNING = 2


class TooManyRuns(Exception):
    """Two agent jobs are already in flight."""

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    slug TEXT NOT NULL,
    project_title TEXT NOT NULL,
    action_id TEXT NOT NULL,
    action_label TEXT NOT NULL,
    status TEXT NOT NULL,
    path_json TEXT NOT NULL,
    steps_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    error TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = _connect()
    try:
        conn.execute(_SCHEMA)
        conn.execute(
            """
            UPDATE runs
            SET status = 'interrupted',
                error = 'The server stopped before this run finished.',
                updated_at = ?
            WHERE status IN ('running', 'stopping')
            """,
            (now(),),
        )
        conn.commit()
    finally:
        conn.close()


def create_run(
    *,
    slug: str,
    project_title: str,
    action_id: str,
    action_label: str,
    path: dict,
) -> dict:
    run_id = uuid.uuid4().hex[:12]
    timestamp = now()
    with _LOCK:
        conn = _connect()
        try:
            running = conn.execute(
                "SELECT COUNT(*) FROM runs WHERE status IN ('running', 'stopping')"
            ).fetchone()[0]
            if running >= MAX_RUNNING:
                raise TooManyRuns()
            conn.execute(
                """
                INSERT INTO runs (
                    id, slug, project_title, action_id, action_label, status,
                    path_json, steps_json, result_json, error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'running', ?, '[]', '{}', '', ?, ?)
                """,
                (
                    run_id,
                    slug,
                    project_title,
                    action_id,
                    action_label,
                    json.dumps(path),
                    timestamp,
                    timestamp,
                ),
            )
            conn.commit()
        finally:
            conn.close()
    return get_run(run_id)


def save_progress(run_id: str, steps: list[dict], result: dict | None = None) -> None:
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                """
                UPDATE runs
                SET steps_json = ?, result_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (json.dumps(steps), json.dumps(result or {}), now(), run_id),
            )
            conn.commit()
        finally:
            conn.close()


def finish_run(run_id: str, *, status: str, steps: list[dict], result: dict, error: str = "") -> None:
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                """
                UPDATE runs
                SET status = ?, steps_json = ?, result_json = ?, error = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, json.dumps(steps), json.dumps(result), error, now(), run_id),
            )
            conn.commit()
        finally:
            conn.close()


def request_stop(run_id: str) -> dict | None:
    """Ask a running job to stop. The worker finishes the paper it is already reading."""
    with _LOCK:
        conn = _connect()
        try:
            row = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                return None
            if row["status"] == "running":
                conn.execute(
                    """
                    UPDATE runs
                    SET status = 'stopping', updated_at = ?
                    WHERE id = ? AND status = 'running'
                    """,
                    (now(), run_id),
                )
                conn.commit()
        finally:
            conn.close()
    return get_run(run_id)


def list_runs() -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT id, slug, project_title, action_id, action_label, status,
                   error, created_at, updated_at
            FROM runs
            ORDER BY created_at DESC
            """
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def delete_run(run_id: str) -> bool:
    with _LOCK:
        conn = _connect()
        try:
            cursor = conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
            conn.commit()
            removed = cursor.rowcount > 0
        finally:
            conn.close()
    if removed:
        delete_log(run_id)
    return removed


def delete_all_runs() -> int:
    with _LOCK:
        conn = _connect()
        try:
            cursor = conn.execute("DELETE FROM runs")
            conn.commit()
            removed = cursor.rowcount
        finally:
            conn.close()
    delete_all_logs()
    return removed


def get_run(run_id: str) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    record = dict(row)
    record["path"] = json.loads(record.pop("path_json"))
    record["steps"] = json.loads(record.pop("steps_json"))
    record["result"] = json.loads(record.pop("result_json"))
    return record


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn
