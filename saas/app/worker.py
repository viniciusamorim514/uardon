from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
from pathlib import Path

from .db import get_job, update_job, utc_now
from .settings import PYTHON, ROOT


_lock = threading.Lock()
_active: set[str] = set()
_cancelled: set[str] = set()
_processes: dict[str, subprocess.Popen] = {}


def _python_exe() -> str:
    return str(PYTHON if PYTHON.exists() else Path(sys.executable))


def _progress_from_line(line: str, current: int) -> tuple[int, str]:
    lower = line.lower()
    download_match = re.search(r"\[download\]\s+(\d+(?:\.\d+)?)%", line)
    if download_match:
        pct = float(download_match.group(1))
        return max(current, 4 + int(min(1.0, pct / 100) * 16)), f"Baixando video {pct:.1f}%"
    rules = [
        (10, "1/5", "Preparando fonte"),
        (24, "2/5", "Baixando transcricao"),
        (44, "3/5", "Calculando candidatos"),
        (58, "avaliando contexto editorial", "IA avaliando contexto"),
        (66, "4/5", "Selecionando cortes"),
        (78, "5/5", "Renderizando"),
        (94, "sincronia ok", "Validando audio"),
        (98, "corte criado:", "Salvando corte"),
        (100, "postar agora:", "Pacote pronto"),
    ]
    for value, needle, stage in rules:
        if needle in lower and value > current:
            return value, stage
    frame_match = re.search(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)", line)
    if frame_match and current < 96:
        return max(current, 82), "Renderizando"
    return current, ""


def enqueue_job(job_id: str) -> None:
    thread = threading.Thread(target=_run_job, args=(job_id,), daemon=True)
    thread.start()


def cancel_job(job_id: str) -> bool:
    with _lock:
        _cancelled.add(job_id)
        process = _processes.get(job_id)
    if process and process.poll() is None:
        process.terminate()
        update_job(job_id, status="cancelled", stage="Cancelado", progress=0, error="", finished_at=utc_now())
        return True
    job = get_job(job_id)
    if job and job.get("status") in {"queued", "running"}:
        update_job(job_id, status="cancelled", stage="Cancelado", progress=0, error="", finished_at=utc_now())
        return True
    return False


def _run_job(job_id: str) -> None:
    with _lock:
        if job_id in _active:
            return
        _active.add(job_id)
    try:
        job = get_job(job_id)
        if not job:
            return
        request = job["request"]
        cmd = [
            _python_exe(),
            str(ROOT / "src" / "opus_local.py"),
            "--url",
            str(request["url"]),
            "--count",
            str(request.get("count", 3)),
            "--min-score",
            str(request.get("min_score", 75)),
            "--min-duration",
            str(request.get("min_duration", 45)),
            "--max-duration",
            str(request.get("max_duration", 90)),
            "--quality",
            str(request.get("quality", "alta")),
            "--editorial-ai",
            str(request.get("ai_mode", "auto")),
        ]
        if request.get("preview_only"):
            cmd.append("--preview-only")

        update_job(job_id, status="running", stage="Iniciando", progress=2, started_at=utc_now(), log=[])
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        process = subprocess.Popen(
            cmd,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            bufsize=1,
        )
        with _lock:
            _processes[job_id] = process
        logs: list[str] = []
        created_videos: list[str] = []
        posting_pack = ""
        index_path = ""
        progress = 2
        stage = "Iniciando"
        assert process.stdout is not None
        for line in process.stdout:
            clean = line.rstrip()
            if clean:
                logs.append(clean)
                lower_clean = clean.lower()
                if lower_clean.startswith("postar agora:"):
                    posting_pack = clean.split(":", 1)[1].strip()
                elif lower_clean.startswith("indice:"):
                    index_path = clean.split(":", 1)[1].strip()
                elif clean.lower().endswith(".mp4") and Path(clean.strip()).suffix.lower() == ".mp4":
                    created_videos.append(clean.strip())
            next_progress, next_stage = _progress_from_line(clean, progress)
            if next_progress != progress or next_stage:
                progress = next_progress
                stage = next_stage or stage
            if len(logs) % 5 == 0 or next_stage:
                update_job(job_id, progress=progress, stage=stage, log=logs)
        code = process.wait()
        was_cancelled = job_id in _cancelled
        if was_cancelled:
            update_job(
                job_id,
                status="cancelled",
                stage="Cancelado",
                progress=0,
                finished_at=utc_now(),
                log=logs,
                result={},
            )
        elif code == 0:
            update_job(
                job_id,
                status="completed",
                stage="Concluido",
                progress=100,
                finished_at=utc_now(),
                log=logs,
                result={
                    "outputs_dir": str(ROOT / "outputs" / "_postar_agora"),
                    "posting_pack": posting_pack,
                    "index": index_path,
                    "videos": created_videos,
                },
            )
        else:
            update_job(
                job_id,
                status="failed",
                stage="Erro",
                error=f"Processo terminou com codigo {code}",
                finished_at=utc_now(),
                log=logs,
            )
    except Exception as exc:
        update_job(job_id, status="failed", stage="Erro", error=str(exc), finished_at=utc_now())
    finally:
        with _lock:
            _active.discard(job_id)
            _processes.pop(job_id, None)
            _cancelled.discard(job_id)
