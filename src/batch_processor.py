"""Job queue manager for batch processing.

Manages persistent job queue stored in studio_db.json.
Processes jobs FIFO with status tracking.

Job statuses:
  - pending: waiting to process
  - rendering: currently processing
  - validating: checking output
  - ready: completed successfully
  - failed: processing failed

Usage:
    processor = BatchProcessor()
    processor.add_job("https://youtube.com/watch?v=...")
    status = processor.process_next()  # Process one job

    # Or in web_app.py, expand process_queue() to use this
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional
from enum import Enum

try:
    from observability import log_event
except ImportError:
    # Fallback if observability not available
    def log_event(*args, **kwargs):
        pass


class JobStatus(Enum):
    PENDING = "pending"
    RENDERING = "rendering"
    VALIDATING = "validating"
    READY = "ready"
    FAILED = "failed"


@dataclass
class Job:
    """A single processing job."""
    id: str
    url: str
    status: str = JobStatus.PENDING.value
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    output_dir: Optional[str] = None
    error: Optional[str] = None
    clips_count: int = 3
    quality: str = "alta"
    priority: str = "normal"  # high, normal, low
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Job:
        """Criar Job a partir de dicionário, ignorando campos desconhecidos."""
        # Compatibilidade: 'count' -> 'clips_count'
        if 'count' in data and 'clips_count' not in data:
            data['clips_count'] = data.pop('count')

        # Remover campos desconhecidos
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}

        return cls(**filtered_data)


class BatchProcessor:
    """Manages persistent job queue."""

    def __init__(self, db_path: Path | None = None):
        self.root = Path(__file__).resolve().parents[1]
        self.db_path = db_path or (self.root / "outputs" / "studio_db.json")
        self.lock_file = self.db_path.parent / ".job_queue.lock"
        self._ensure_db()

    def _ensure_db(self):
        """Ensure database file exists."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.db_path.exists():
            self._write_db({"jobs": [], "stats": {"total": 0, "completed": 0, "failed": 0}})

    def _read_db(self) -> dict:
        """Read job database."""
        try:
            if self.db_path.exists():
                data = json.loads(self.db_path.read_text(encoding="utf-8"))
                # Garantir que stats existe
                if "stats" not in data:
                    data["stats"] = {"total": 0, "completed": 0, "failed": 0}
                return data
        except:
            pass
        return {"jobs": [], "stats": {"total": 0, "completed": 0, "failed": 0}}

    def _write_db(self, data: dict) -> None:
        """Write job database."""
        self.db_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def add_job(
        self,
        url: str,
        clips_count: int = 3,
        quality: str = "alta",
        priority: str = "normal",
        tags: list[str] | None = None,
    ) -> str:
        """Add a new job to queue. Returns job ID."""
        db = self._read_db()
        job_id = f"job-{datetime.now().strftime('%Y%m%d%H%M%S')}-{len(db['jobs'])}"

        job = Job(
            id=job_id,
            url=url,
            clips_count=clips_count,
            quality=quality,
            priority=priority,
            tags=tags or [],
        )
        db["jobs"].append(job.to_dict())
        db["stats"]["total"] += 1

        # Re-sort by priority (high first, then normal, then low)
        priority_order = {"high": 0, "normal": 1, "low": 2}
        db["jobs"].sort(
            key=lambda j: (
                priority_order.get(j.get("priority", "normal"), 1),
                j.get("created_at", ""),
            )
        )

        self._write_db(db)

        # Log job submission (if not already logged by web_app.py, this provides fallback)
        log_event("job_enqueued", {
            "job_id": job_id,
            "url": url,
            "priority": priority,
            "clips_count": clips_count,
            "quality": quality,
            "tags": tags or []
        })

        return job_id

    def get_next_pending(self) -> Optional[Job]:
        """Get next pending job (FIFO with priority)."""
        db = self._read_db()
        for job_data in db["jobs"]:
            if job_data["status"] == JobStatus.PENDING.value:
                return Job.from_dict(job_data)
        return None

    def update_job_status(self, job_id: str, status: JobStatus, error: Optional[str] = None) -> bool:
        """Update job status. Returns True if found."""
        db = self._read_db()
        for job_data in db["jobs"]:
            if job_data["id"] == job_id:
                job_data["status"] = status.value
                if status == JobStatus.RENDERING:
                    job_data["started_at"] = datetime.now().isoformat()
                elif status in (JobStatus.READY, JobStatus.FAILED):
                    job_data["completed_at"] = datetime.now().isoformat()
                if error:
                    job_data["error"] = error
                if status == JobStatus.READY:
                    db["stats"]["completed"] += 1
                elif status == JobStatus.FAILED:
                    db["stats"]["failed"] += 1
                self._write_db(db)

                # Log job status transition
                if status in (JobStatus.READY, JobStatus.FAILED):
                    # Calculate duration if we have timestamps
                    duration_s = 0.0
                    if job_data.get("started_at"):
                        try:
                            started = datetime.fromisoformat(job_data["started_at"])
                            completed = datetime.fromisoformat(job_data["completed_at"])
                            duration_s = (completed - started).total_seconds()
                        except (ValueError, TypeError):
                            pass

                    log_event("job_completed", {
                        "job_id": job_id,
                        "duration_s": duration_s,
                        "clips_rendered": job_data.get("clips_count", 3),
                        "quality": job_data.get("quality", "alta"),
                        "status": status.value,
                        "error": error if status == JobStatus.FAILED else None
                    })

                return True
        return False

    def set_output_dir(self, job_id: str, output_dir: str) -> bool:
        """Set output directory for a job."""
        db = self._read_db()
        for job_data in db["jobs"]:
            if job_data["id"] == job_id:
                job_data["output_dir"] = output_dir
                self._write_db(db)
                return True
        return False

    def get_job(self, job_id: str) -> Optional[Job]:
        """Get a specific job by ID."""
        db = self._read_db()
        for job_data in db["jobs"]:
            if job_data["id"] == job_id:
                return Job.from_dict(job_data)
        return None

    def list_jobs(self, status: Optional[JobStatus] = None, limit: int = 50) -> list[Job]:
        """List jobs, optionally filtered by status."""
        db = self._read_db()
        jobs = [Job.from_dict(j) for j in db["jobs"]]
        if status:
            jobs = [j for j in jobs if j.status == status.value]
        return jobs[:limit]

    def get_stats(self) -> dict:
        """Get queue statistics."""
        db = self._read_db()
        return db.get("stats", {})

    def archive_job(self, job_id: str) -> bool:
        """Move completed job to archive."""
        db = self._read_db()
        job_data = next((j for j in db["jobs"] if j["id"] == job_id), None)
        if not job_data:
            return False

        # Move to archive
        archive_dir = self.db_path.parent / "archive" / job_data["created_at"][:10]
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_file = archive_dir / f"{job_id}.json"
        archive_file.write_text(json.dumps(job_data, indent=2, ensure_ascii=False), encoding="utf-8")

        # Remove from active queue
        db["jobs"] = [j for j in db["jobs"] if j["id"] != job_id]
        self._write_db(db)
        return True

    def clear_old_jobs(self, days: int = 7) -> int:
        """Archive jobs older than N days. Returns count archived."""
        from datetime import timedelta

        db = self._read_db()
        cutoff = datetime.now() - timedelta(days=days)
        archived = 0

        for job_data in db["jobs"][:]:
            if job_data["status"] in [JobStatus.READY.value, JobStatus.FAILED.value]:
                created = datetime.fromisoformat(job_data["created_at"])
                if created < cutoff:
                    self.archive_job(job_data["id"])
                    archived += 1

        return archived


if __name__ == "__main__":
    # Example usage
    processor = BatchProcessor()

    # Add some jobs
    job_id_1 = processor.add_job("https://youtube.com/watch?v=TEST1", priority="high")
    job_id_2 = processor.add_job("https://youtube.com/watch?v=TEST2")
    job_id_3 = processor.add_job("https://youtube.com/watch?v=TEST3", priority="low")

    print(f"Added jobs: {job_id_1}, {job_id_2}, {job_id_3}")

    # Get stats
    stats = processor.get_stats()
    print(f"Stats: {stats}")

    # Process first job
    next_job = processor.get_next_pending()
    if next_job:
        print(f"Next job: {next_job.url}")
        processor.update_job_status(next_job.id, JobStatus.RENDERING)

    # List all jobs
    all_jobs = processor.list_jobs()
    for job in all_jobs:
        print(f"  {job.id}: {job.status} {job.url}")
