from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
DB_PATH = OUTPUTS / "studio_db.json"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def empty_db() -> dict[str, list[dict[str, Any]]]:
    return {"jobs": [], "candidate_reports": [], "cuts": []}


def load_db() -> dict[str, list[dict[str, Any]]]:
    if not DB_PATH.exists():
        return empty_db()
    try:
        data = json.loads(DB_PATH.read_text(encoding="utf-8"))
    except Exception:
        return empty_db()
    db = empty_db()
    for key in db:
        value = data.get(key, [])
        db[key] = value if isinstance(value, list) else []
    return db


def save_db(db: dict[str, list[dict[str, Any]]]) -> None:
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    tmp = DB_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(DB_PATH)


def append_record(kind: str, record: dict[str, Any], limit: int = 120) -> None:
    db = load_db()
    item = {"created_at": now_iso(), **record}
    db.setdefault(kind, []).insert(0, item)
    db[kind] = db[kind][:limit]
    save_db(db)


def record_job(url: str, status: str, **extra: Any) -> None:
    append_record("jobs", {"url": url, "status": status, **extra})


def start_job(url: str, **extra: Any) -> str:
    job_id = datetime.now().strftime("%Y%m%d%H%M%S") + "-" + uuid4().hex[:8]
    append_record(
        "jobs",
        {
            "id": job_id,
            "url": url,
            "status": "rodando",
            "started_at": now_iso(),
            **extra,
        },
    )
    return job_id


def update_job(job_id: str, status: str, **extra: Any) -> None:
    db = load_db()
    jobs = db.setdefault("jobs", [])
    for job in jobs:
        if str(job.get("id", "")) == str(job_id):
            job.update({"status": status, "updated_at": now_iso(), **extra})
            if status in {"concluido", "erro"}:
                job["finished_at"] = now_iso()
            save_db(db)
            return
    append_record("jobs", {"id": job_id, "status": status, **extra})


def record_candidate_report(url: str, report_path: Path, candidates: int) -> None:
    append_record(
        "candidate_reports",
        {
            "url": url,
            "report": str(report_path),
            "folder": str(report_path.parent),
            "candidates": candidates,
        },
    )


def record_cut(url: str, candidate: dict[str, Any], video_path: Path, pack_dir: Path | None, quality: dict[str, Any] | None) -> None:
    append_record(
        "cuts",
        {
            "url": url,
            "rank": candidate.get("rank"),
            "score": candidate.get("score"),
            "headline": candidate.get("headline"),
            "start": candidate.get("start"),
            "duration": candidate.get("duration"),
            "video": str(video_path),
            "folder": str(video_path.parent),
            "pack": str(pack_dir) if pack_dir else "",
            "quality_status": (quality or {}).get("status", ""),
            "quality_score": (quality or {}).get("score", ""),
        },
    )


def read_history() -> dict[str, list[dict[str, Any]]]:
    return load_db()
