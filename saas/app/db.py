from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from .settings import DB_PATH, ensure_dirs


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.execute(
            """
            create table if not exists jobs (
                id text primary key,
                user_id text not null,
                url text not null,
                status text not null,
                stage text not null,
                progress integer not null default 0,
                request_json text not null,
                result_json text not null default '{}',
                error text not null default '',
                log text not null default '',
                created_at text not null,
                updated_at text not null,
                started_at text,
                finished_at text
            )
            """
        )
        conn.execute("create index if not exists idx_jobs_user_created on jobs(user_id, created_at desc)")


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    data = dict(row)
    for key in ("request_json", "result_json"):
        data[key.replace("_json", "")] = json.loads(data.pop(key) or "{}")
    data["log"] = json.loads(data.get("log") or "[]")
    return data


def create_job(job_id: str, user_id: str, url: str, request: dict) -> dict:
    now = utc_now()
    with connect() as conn:
        conn.execute(
            """
            insert into jobs
            (id, user_id, url, status, stage, progress, request_json, created_at, updated_at)
            values (?, ?, ?, 'queued', 'Na fila', 0, ?, ?, ?)
            """,
            (job_id, user_id, url, json.dumps(request, ensure_ascii=False), now, now),
        )
        return row_to_dict(conn.execute("select * from jobs where id = ?", (job_id,)).fetchone()) or {}


def get_job(job_id: str, user_id: str | None = None) -> dict | None:
    with connect() as conn:
        if user_id:
            row = conn.execute("select * from jobs where id = ? and user_id = ?", (job_id, user_id)).fetchone()
        else:
            row = conn.execute("select * from jobs where id = ?", (job_id,)).fetchone()
        return row_to_dict(row)


def list_jobs(user_id: str, limit: int = 30) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "select * from jobs where user_id = ? order by created_at desc limit ?",
            (user_id, limit),
        ).fetchall()
        return [row_to_dict(row) or {} for row in rows]


def update_job(job_id: str, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = utc_now()
    if "result" in fields:
        fields["result_json"] = json.dumps(fields.pop("result"), ensure_ascii=False)
    if "request" in fields:
        fields["request_json"] = json.dumps(fields.pop("request"), ensure_ascii=False)
    if "log" in fields and not isinstance(fields["log"], str):
        fields["log"] = json.dumps(fields["log"][-220:], ensure_ascii=False)
    assignments = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [job_id]
    with connect() as conn:
        conn.execute(f"update jobs set {assignments} where id = ?", values)
