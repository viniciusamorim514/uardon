from __future__ import annotations

import json
import os
import csv
import re
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from create_cut_from_source import ffmpeg_path
from hw_encoder import video_encoder_args
from local_db import read_history
from radar import add_source, mark_item, read_radar, scan_all
from analyze_tiktok_metrics import analyze as analyze_tiktok_metrics
from youtube_to_cut import download_youtube_section
from batch_processor import BatchProcessor, JobStatus
from hook_variants import generate_hook_variants
from observability import log_event, get_summary


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
OUTPUTS = ROOT / "outputs"
POST_NOW = OUTPUTS / "_postar_agora"
LEARNING_DIR = OUTPUTS / "tiktok-analytics"
LEARNING_JSON = LEARNING_DIR / "aprendizado.json"
LEARNING_MD = LEARNING_DIR / "aprendizado.md"
ANALYTICS_CSV = ROOT / "analytics.csv"
REPORTS = OUTPUTS / "relatorios" / "opus-local"
PREVIEW = OUTPUTS / "relatorios" / "pre-aprovacao"
FAST_PREVIEW = OUTPUTS / "relatorios" / "preview-video"
WEB = ROOT / "web"
HOST = os.getenv("STUDIO_HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8787"))
PODCAST_RECENT_DAYS = 15
PODCAST_RECENT_SECONDS = PODCAST_RECENT_DAYS * 24 * 60 * 60


batch_processor = BatchProcessor(OUTPUTS / "studio_db.json")

state = {
    "running": False,
    "status": "Pronto",
    "stage": "Aguardando link",
    "progress": 0,
    "log": [],
    "queue": [],
    "current_url": "",
    "render_duration": 0.0,
    "last_render_log_second": -1,
}
state_lock = threading.Lock()
worker_thread: threading.Thread | None = None
radar_thread: threading.Thread | None = None


def default_payload(url: str) -> dict:
    return {
        "url": url,
        "count": 3,
        "min_score": 75,
        "min_duration": 60,
        "max_duration": 90,
        "ai_mode": "auto",
        "quality": "alta",
        "focus": "auto",
    }


def short_payload(url: str) -> dict:
    return {
        "url": url,
        "count": 1,
        "min_score": 60,
        "min_duration": 20,
        "max_duration": 90,
        "ai_mode": "auto",
        "quality": "alta",
        "focus": "auto",
    }


def is_recent_podcast_item(item: dict) -> bool:
    published_ts = float(item.get("published_ts") or 0)
    if published_ts <= 0:
        return True
    return published_ts >= time.time() - PODCAST_RECENT_SECONDS


def filter_radar(kind: str = "podcast") -> dict:
    kind = "shorts" if str(kind).lower() in {"short", "shorts"} else "podcast"
    data = read_radar()
    sources = [source for source in data.get("sources", []) if source.get("content_type", "podcast") == kind]
    source_ids = {source.get("id") for source in sources}
    items = []
    for item in data.get("items", []):
        text = f"{item.get('title', '')} {item.get('url', '')}".lower()
        inferred_short = "/shorts/" in text or "#shorts" in text
        item_type = item.get("content_type") or ("shorts" if inferred_short or item.get("source_type") == "shorts" else "podcast")
        if kind == "shorts":
            if item.get("source_id") in source_ids or item_type == "shorts":
                items.append(item)
        elif item.get("source_id") in source_ids and item_type != "shorts" and is_recent_podcast_item(item):
            items.append(item)
    result = dict(data)
    items = sorted(items, key=lambda item: (int(item.get("episode_score") or 0), float(item.get("published_ts") or 0)), reverse=True)
    result["sources"] = sources
    result["items"] = items
    result["kind"] = kind
    result["recent_days"] = PODCAST_RECENT_DAYS if kind == "podcast" else None
    return result


def set_state(**kwargs) -> None:
    with state_lock:
        state.update(kwargs)


def append_log(line: str) -> None:
    clean = line.strip()
    if clean.startswith("frame=") and "Lsize=" not in clean:
        return
    with state_lock:
        state["log"].append(line)
        state["log"] = state["log"][-140:]


def hms_to_seconds(hours: str, minutes: str, seconds: str) -> float:
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def progress_from_line(line: str) -> None:
    lower = line.lower()
    auto_steps = [
        (14, "auto 1/4", "Analisando candidatos"),
        (58, "auto 2/4", "Selecionando melhores trechos"),
        (72, "auto 3/4", "Renderizando cortes"),
        (100, "auto 4/4", "Cortes prontos"),
    ]
    for value, needle, label in auto_steps:
        if needle in lower:
            set_state(progress=value, stage=label)
            return
    duration_match = re.search(r"duracao:\s*(\d+(?:\.\d+)?)s", lower)
    if duration_match:
        set_state(render_duration=float(duration_match.group(1)), progress=76, stage="Renderizando corte 0%")
        return
    frame_match = re.search(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)", line)
    if frame_match:
        elapsed = hms_to_seconds(*frame_match.groups())
        with state_lock:
            duration = float(state.get("render_duration") or 0)
            last_second = int(state.get("last_render_log_second", -1))
        if duration > 0:
            render_percent = max(0, min(100, int((elapsed / duration) * 100)))
            mapped_progress = 76 + int(render_percent * 0.20)
            updates = {"progress": mapped_progress, "stage": f"Renderizando corte {render_percent}%"}
            if int(elapsed) >= last_second + 10:
                updates["last_render_log_second"] = int(elapsed)
            set_state(**updates)
        return
    if "sincronia ok" in lower:
        set_state(progress=97, stage="Validando audio e video")
        return
    if "corte criado:" in lower:
        set_state(progress=99, stage="Corte criado")
        return
    if "postar agora:" in lower:
        set_state(progress=100, stage="Pacote pronto para postar")
        return
    download_match = re.search(r"\[download\]\s+(\d+(?:\.\d+)?)%", line)
    if download_match:
        download_percent = float(download_match.group(1))
        mapped_progress = 3 + int(min(1.0, download_percent / 100) * 17)
        set_state(progress=mapped_progress, stage=f"Baixando video {download_percent:.1f}%")
        return
    steps = [
        (10, "1/5", "Preparando video fonte"),
        (25, "2/5", "Baixando transcricao"),
        (45, "3/5", "Calculando score dos trechos"),
        (65, "4/5", "Selecionando candidatos"),
        (82, "5/5", "Renderizando e validando"),
        (18, "1/4", "Baixando transcricao"),
        (46, "2/4", "Calculando candidatos"),
        (68, "3/4", "IA avaliando contexto"),
        (96, "4/4", "Salvando pre-aprovacao"),
        (12, "baixando", "Baixando video"),
        (28, "subtitles", "Baixando transcricao"),
        (48, "avaliando contexto editorial", "IA avaliando contexto"),
        (58, "analisando movimento", "Analisando movimento visual"),
        (72, "pre-aprovacao", "Gerando pre-aprovacao"),
        (86, "sincronia ok", "Validando audio e video"),
        (96, "pronto", "Finalizando pacote"),
    ]
    with state_lock:
        current = int(state.get("progress", 0))
    for value, needle, label in steps:
        if needle in lower and value > current:
            set_state(progress=value, stage=label)
            break


def run_command(cmd: list[str]) -> int:
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
    assert process.stdout
    for line in process.stdout:
        progress_from_line(line)
        append_log(line)
    return process.wait()


def build_opus_command(payload: dict) -> list[str]:
    if payload.get("preview_only"):
        return [
            str(PYTHON),
            str(ROOT / "src" / "analyze_candidates_fast.py"),
            "--url",
            str(payload["url"]).strip(),
            "--count",
            str(max(10, int(payload.get("count", 3)))),
            "--min-score",
            str(payload.get("min_score", 75)),
            "--min-duration",
            str(payload.get("min_duration", 60)),
            "--max-duration",
            str(payload.get("max_duration", 90)),
            "--editorial-ai",
            str(payload.get("ai_mode", "auto")),
        ]
    cmd = [
        str(PYTHON),
        str(ROOT / "src" / "auto_pipeline.py"),
        "--url",
        str(payload["url"]).strip(),
        "--count",
        str(payload.get("count", 3)),
        "--min-score",
        str(payload.get("min_score", 75)),
        "--min-duration",
        str(payload.get("min_duration", 60)),
        "--max-duration",
        str(payload.get("max_duration", 90)),
        "--editorial-ai",
        str(payload.get("ai_mode", "auto")),
        "--quality",
        str(payload.get("quality", "alta")),
        "--focus",
        str(payload.get("focus", "auto")),
    ]
    if payload.get("allow_low_quality"):
        cmd.append("--allow-low-quality")
    return cmd


def process_queue() -> None:
    set_state(running=True, status="Rodando", progress=3, stage="Preparando")
    try:
        while True:
            with state_lock:
                if not state["queue"]:
                    break
                payload = state["queue"].pop(0)
                state["current_url"] = str(payload.get("url", "")).strip()
            set_state(progress=3, stage="Preparando", status="Rodando", render_duration=0.0, last_render_log_second=-1)
            append_log("\n=== Novo job ===\n")
            append_log(f"URL: {payload.get('url')}\n")
            code = run_command(build_opus_command(payload))
            if code != 0:
                set_state(status="Erro", stage="Falha no processamento")
                break
            set_state(progress=100, stage="Concluido", status="Pronto")
    finally:
        set_state(running=False, current_url="")


def enqueue_payload(payload: dict) -> tuple[bool, str]:
    global worker_thread
    url = str(payload.get("url", "")).strip()
    if not url:
        return False, "URL vazia"

    # Check for duplicates using BatchProcessor
    existing_jobs = batch_processor.list_jobs()
    duplicate_job = any(j.url == url and j.status in ["pending", "rendering"] for j in existing_jobs)

    if duplicate_job:
        return False, "Este link ja esta rodando ou na fila."

    # Add job using BatchProcessor (persistent queue)
    job_id = batch_processor.add_job(
        url,
        clips_count=int(payload.get("count", 3)),
        quality=str(payload.get("quality", "alta")),
        tags=payload.get("tags", []),
    )

    with state_lock:
        state["queue"].append({"job_id": job_id, **payload})
        should_start = not state["running"]

    if should_start:
        worker_thread = threading.Thread(target=process_queue, daemon=True)
        worker_thread.start()

    return True, job_id


def radar_monitor_loop() -> None:
    while True:
        try:
            data = scan_all()
            enqueue_auto_radar_items(data)
        except Exception as exc:
            append_log(f"[radar] erro no monitoramento: {exc}\n")
        time.sleep(15 * 60)


def enqueue_auto_radar_items(data: dict) -> int:
    sources_by_id = {source["id"]: source for source in data.get("sources", []) if source.get("auto_cut")}
    queued = 0
    for item in data.get("items", []):
        source = sources_by_id.get(item.get("source_id"))
        if not source:
            continue
        if not (item.get("is_new") or item.get("status") == "novo"):
            continue
        is_short = item.get("content_type") == "shorts" or source.get("content_type") == "shorts"
        if not is_short and not is_recent_podcast_item(item):
            continue
        payload = short_payload(str(item.get("url", ""))) if is_short else default_payload(str(item.get("url", "")))
        ok, _error = enqueue_payload(payload)
        if ok:
            queued += 1
            mark_item(str(item.get("id", "")), "na fila")
    return queued


def render_async(cmd: list[str], rank: int) -> None:
    try:
        code = run_command(cmd)
        if code == 0:
            set_state(running=False, status="Pronto", progress=100, stage=f"Candidato {rank} renderizado", render_duration=0.0, last_render_log_second=-1)
        else:
            set_state(running=False, status="Erro", stage=f"Falha ao renderizar candidato {rank}", render_duration=0.0, last_render_log_second=-1)
    except Exception as exc:
        append_log(f"\n[erro] {exc}\n")
        set_state(running=False, status="Erro", stage=f"Falha ao renderizar candidato {rank}", render_duration=0.0, last_render_log_second=-1)


def latest_candidates_path() -> Path | None:
    folders: list[Path] = []
    for base in (PREVIEW, OUTPUTS / "pre-aprovacao"):
        if base.exists():
            folders.extend([path for path in base.iterdir() if path.is_dir()])
    for folder in sorted(folders, key=lambda path: path.stat().st_mtime, reverse=True):
        candidate_file = folder / "candidatos.json"
        if candidate_file.exists():
            return candidate_file
    return None


def read_candidates() -> dict:
    path = latest_candidates_path()
    if not path:
        return {"path": "", "candidates": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    data["path"] = str(path)
    return data


def timestamp_to_seconds(value: str) -> float:
    parts = str(value).split(":")
    if len(parts) != 3:
        return 0.0
    hours, minutes, seconds = parts
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def candidate_by_rank(rank: int) -> tuple[dict, dict, Path] | None:
    path = latest_candidates_path()
    if not path:
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    for candidate in data.get("candidates", []):
        if int(candidate.get("rank", 0)) == rank:
            return data, candidate, path
    return None


def make_candidate_preview(rank: int) -> Path:
    loaded = candidate_by_rank(rank)
    if not loaded:
        raise RuntimeError("Candidato nao encontrado.")
    data, candidate, _path = loaded
    source_video_raw = str(data.get("source_video", "")).strip()
    source_video = Path(source_video_raw) if source_video_raw else None
    downloaded = False
    if source_video and not source_video.is_absolute():
        source_video = ROOT / source_video
    if source_video is None or not source_video.exists():
        source_url = str(data.get("source", "")).strip()
        if not source_url:
            raise FileNotFoundError(source_video_raw or "source_video vazio")
        source_video = download_youtube_section(
            source_url,
            str(candidate.get("start", "00:00:00")),
            min(18.0, max(8.0, float(candidate.get("duration", 18)))),
        )
        downloaded = True

    FAST_PREVIEW.mkdir(parents=True, exist_ok=True)
    output = FAST_PREVIEW / f"candidato-{rank:02d}.mp4"
    start = 0.0 if downloaded else max(0.0, timestamp_to_seconds(candidate.get("start", "00:00:00")))
    duration = min(18.0, max(8.0, float(candidate.get("duration", 18))))
    cmd = [
        ffmpeg_path(),
        "-y",
        "-ss",
        f"{start:.2f}",
        "-i",
        str(source_video),
        "-t",
        f"{duration:.2f}",
        "-vf",
        "scale=720:-2,fps=30,format=yuv420p",
        "-af",
        "loudnorm=I=-16:LRA=9:TP=-1.5",
        *video_encoder_args(crf="24", maxrate="8000k", bufsize="16000k"),
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(output),
    ]
    try:
        subprocess.run(cmd, cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
    finally:
        if downloaded:
            try:
                source_video.unlink()
            except OSError:
                pass
    return output


def read_score(folder: Path) -> str:
    for name in ("score-viral.txt", "score.txt"):
        path = folder / name
        if path.exists():
            text = path.read_text(encoding="utf-8-sig", errors="ignore")
            for line in text.splitlines():
                if "score" in line.lower():
                    value = line.split(":", 1)[-1] if ":" in line else line.split("=", 1)[-1]
                    return value.strip()[:16]
    return "-"


def read_quality(folder: Path) -> dict:
    path = folder / "qualidade.json"
    if not path.exists():
        return {"status": "nao analisado", "score": "-", "warnings": [], "issues": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "erro", "score": "-", "warnings": [], "issues": []}
    return {
        "status": str(data.get("status", "nao analisado")),
        "score": data.get("score", "-"),
        "warnings": data.get("warnings", []),
        "issues": data.get("issues", []),
    }


def read_videos() -> list[dict]:
    items = []
    seen: set[tuple[int, str]] = set()
    videos = sorted(
        OUTPUTS.glob("**/*.mp4"),
        key=lambda path: ("_postar_agora" in path.parts, path.stat().st_mtime),
        reverse=True,
    )
    for video in videos:
        if ".work" in video.parts:
            continue
        folder = video.parent
        publication = folder / "publicacao.txt"
        publication_text = publication.read_text(encoding="utf-8-sig", errors="ignore") if publication.exists() else ""
        dedupe_key = (video.stat().st_size, re.sub(r"\s+", " ", publication_text).strip().lower()[:140])
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        quality = read_quality(folder)
        items.append(
            {
                "video": str(video),
                "name": folder.name.replace("-", " "),
                "folder": str(folder),
                "score": read_score(folder),
                "quality_status": quality["status"],
                "quality_score": quality["score"],
                "quality_issues": quality["issues"],
                "quality_warnings": quality["warnings"],
                "publication": publication_text,
            }
        )
        if len(items) >= 24:
            break
    return items


def numeric_score(value: object) -> int:
    match = re.search(r"\d+", str(value or ""))
    return int(match.group(0)) if match else 0


def posting_decision(item: dict) -> dict:
    viral_score = numeric_score(item.get("score"))
    quality_score = numeric_score(item.get("quality_score"))
    status = str(item.get("quality_status") or "nao analisado").lower()
    issues = [str(value) for value in item.get("quality_issues", []) if str(value).strip()]
    warnings = [str(value) for value in item.get("quality_warnings", []) if str(value).strip()]

    if status == "reprovado" or quality_score < 60 or issues:
        return {
            "bucket": "nao_postar",
            "decision": "Não postar",
            "decision_class": "danger",
            "reason": "; ".join(issues) or "qualidade tecnica abaixo do minimo",
            "sort": 0,
        }
    if status == "aprovado" and quality_score >= 85 and viral_score >= 80:
        return {
            "bucket": "postar",
            "decision": "Postar",
            "decision_class": "approve",
            "reason": "score viral forte e qualidade tecnica aprovada",
            "sort": 3,
        }
    if quality_score >= 90 and viral_score >= 70 and not issues:
        return {
            "bucket": "postar",
            "decision": "Postar",
            "decision_class": "approve",
            "reason": "qualidade tecnica alta; revisar apenas o contexto antes de subir",
            "sort": 3,
        }
    return {
        "bucket": "revisar",
        "decision": "Revisar",
        "decision_class": "test",
        "reason": "; ".join(warnings) or "precisa revisão humana antes de postar",
        "sort": 2,
    }


def posting_plan() -> dict:
    videos = read_videos()
    enriched = []
    for item in videos:
        decision = posting_decision(item)
        enriched.append({**item, **decision})
    ranked = sorted(
        enriched,
        key=lambda item: (
            int(item.get("sort", 0)),
            1 if item.get("quality_status") == "aprovado" else 0,
            numeric_score(item.get("score")),
            int(item.get("quality_score") or 0) if str(item.get("quality_score")).isdigit() else 0,
        ),
        reverse=True,
    )
    slots = {
        "postar": ["Publicar agora", "Publicar hoje à noite", "Guardar para amanhã", "Reserva"],
        "revisar": ["Revisar antes de postar", "Revisar depois", "Reserva em revisão"],
        "nao_postar": ["Não postar"],
    }
    counters = {"postar": 0, "revisar": 0, "nao_postar": 0}
    items = []
    for index, item in enumerate(ranked[:8]):
        bucket = str(item.get("bucket") or "revisar")
        bucket_slots = slots.get(bucket, slots["revisar"])
        bucket_index = counters.get(bucket, 0)
        counters[bucket] = bucket_index + 1
        slot = bucket_slots[bucket_index] if bucket_index < len(bucket_slots) else bucket_slots[-1]
        items.append({**item, "slot": slot, "priority": index + 1})
    summary = {
        "postar": sum(1 for item in items if item.get("bucket") == "postar"),
        "revisar": sum(1 for item in items if item.get("bucket") == "revisar"),
        "nao_postar": sum(1 for item in items if item.get("bucket") == "nao_postar"),
    }
    return {"items": items, "summary": summary}


def learning_summary(refresh: bool = False) -> dict:
    if refresh or not LEARNING_JSON.exists():
        try:
            analyze_tiktok_metrics()
        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
                "videos": [],
                "learned_rules": {},
                "top_temas": [],
                "top_hashtags": [],
                "top_horarios": [],
                "report": "",
            }
    if not LEARNING_JSON.exists():
        return {
            "ok": False,
            "error": "Sem analytics processado ainda.",
            "videos": [],
            "learned_rules": {},
            "top_temas": [],
            "top_hashtags": [],
            "top_horarios": [],
            "report": "",
        }
    data = json.loads(LEARNING_JSON.read_text(encoding="utf-8"))
    videos = data.get("videos", [])
    rules = data.get("learned_rules", {})
    report = LEARNING_MD.read_text(encoding="utf-8", errors="ignore") if LEARNING_MD.exists() else ""
    return {
        "ok": True,
        "videos": videos[:8],
        "best_video": videos[0] if videos else {},
        "learned_rules": rules,
        "top_temas": data.get("top_temas", [])[:10],
        "top_hashtags": data.get("top_hashtags", [])[:10],
        "top_horarios": data.get("top_horarios", [])[:8],
        "report": report,
        "json_path": str(LEARNING_JSON),
        "md_path": str(LEARNING_MD),
    }


ANALYTICS_FIELDS = [
    "data_publicacao",
    "hora_publicacao",
    "tema",
    "arquivo_video",
    "duracao_s",
    "views_1h",
    "views_24h",
    "views_7d",
    "retencao_media_pct",
    "tempo_medio_s",
    "assistiu_completo_pct",
    "curtidas",
    "comentarios",
    "compartilhamentos",
    "salvamentos",
    "seguidores_ganhos",
    "gancho",
    "hashtags",
    "observacoes",
]


def read_analytics_rows(limit: int = 30) -> list[dict]:
    if not ANALYTICS_CSV.exists():
        return []
    with ANALYTICS_CSV.open("r", encoding="utf-8-sig", newline="") as file:
        rows = [row for row in csv.DictReader(file) if any(str(value or "").strip() for value in row.values())]
    return rows[-limit:][::-1]


def analytics_payload() -> dict:
    return {
        "ok": True,
        "path": str(ANALYTICS_CSV),
        "fields": ANALYTICS_FIELDS,
        "rows": read_analytics_rows(),
    }


def append_analytics_row(payload: dict) -> dict:
    row = {field: str(payload.get(field, "") or "").strip() for field in ANALYTICS_FIELDS}
    if not row["tema"] and not row["gancho"]:
        raise ValueError("Preencha pelo menos tema ou gancho.")
    if not row["data_publicacao"]:
        row["data_publicacao"] = time.strftime("%d/%m/%Y")
    if not row["duracao_s"]:
        row["duracao_s"] = "60"
    ANALYTICS_CSV.parent.mkdir(parents=True, exist_ok=True)
    exists = ANALYTICS_CSV.exists() and ANALYTICS_CSV.stat().st_size > 0
    with ANALYTICS_CSV.open("a", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=ANALYTICS_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow(row)
    learning = learning_summary(refresh=True)
    return {"ok": True, "row": row, "learning": learning}


def safe_open(path_value: str) -> bool:
    path = Path(path_value)
    try:
        resolved = path.resolve()
    except Exception:
        return False
    allowed = [ROOT.resolve(), OUTPUTS.resolve()]
    if not any(str(resolved).lower().startswith(str(base).lower()) for base in allowed):
        return False
    if resolved.exists():
        os.startfile(str(resolved))
        return True
    return False


class Handler(BaseHTTPRequestHandler):
    def log_message(self, _format: str, *_args) -> None:
        return

    def send_json(self, data: object, code: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.serve_file(WEB / "index.html", "text/html; charset=utf-8")
            return
        if parsed.path == "/app.css":
            self.serve_file(WEB / "app.css", "text/css; charset=utf-8")
            return
        if parsed.path == "/app.js":
            self.serve_file(WEB / "app.js", "application/javascript; charset=utf-8")
            return
        if parsed.path == "/dashboard.html":
            self.serve_file(WEB / "dashboard.html", "text/html; charset=utf-8")
            return
        if parsed.path == "/api/state":
            with state_lock:
                snapshot = dict(state)
            self.send_json(snapshot)
            return
        if parsed.path == "/api/candidates":
            self.send_json(read_candidates())
            return
        if parsed.path == "/api/videos":
            self.send_json({"videos": read_videos()})
            return
        if parsed.path == "/api/posting-plan":
            self.send_json(posting_plan())
            return
        if parsed.path == "/api/learning":
            refresh = parse_qs(parsed.query).get("refresh", ["0"])[0] in {"1", "true", "sim"}
            self.send_json(learning_summary(refresh=refresh))
            return
        if parsed.path == "/api/analytics":
            # Return observability metrics
            query_params = parse_qs(parsed.query)
            days = int(query_params.get("days", ["7"])[0])
            event_type = query_params.get("event_type", [None])[0]

            from observability import get_manager
            manager = get_manager()
            metrics = manager.get_metrics(event_type=event_type, days=days)
            self.send_json(metrics)
            return
        if parsed.path == "/api/analytics/events":
            # Return recent events for dashboard
            query_params = parse_qs(parsed.query)
            days = int(query_params.get("days", ["7"])[0])
            limit = int(query_params.get("limit", ["10"])[0])

            from observability import get_manager
            manager = get_manager()
            events = manager.get_events(days=days, limit=limit)
            self.send_json(events)
            return
        if parsed.path == "/api/history":
            self.send_json(read_history())
            return
        if parsed.path == "/api/radar":
            kind = parse_qs(parsed.query).get("kind", ["podcast"])[0]
            self.send_json(filter_radar(kind))
            return
        if parsed.path == "/api/tiktok-status":
            import urllib.request
            chrome_ok = False
            try:
                urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=2)
                chrome_ok = True
            except Exception:
                chrome_ok = False
            self.send_json({"ready": chrome_ok, "chrome_debug": chrome_ok})
            return
        if parsed.path == "/api/jobs":
            # List all jobs with optional status filter
            query_params = parse_qs(parsed.query)
            status_filter = query_params.get("status", [None])[0]
            limit = int(query_params.get("limit", ["50"])[0])
            jobs = batch_processor.list_jobs(limit=limit)
            jobs_data = [
                {
                    "id": j.id,
                    "url": j.url,
                    "status": j.status,
                    "created_at": j.created_at,
                    "completed_at": j.completed_at,
                    "clips_count": j.clips_count,
                    "quality": j.quality,
                    "error": j.error,
                }
                for j in jobs
                if not status_filter or j.status == status_filter
            ]
            self.send_json({
                "jobs": jobs_data,
                "stats": batch_processor.get_stats(),
                "count": len(jobs_data),
            })
            return
        if parsed.path == "/api/open":
            path = parse_qs(parsed.query).get("path", [""])[0]
            self.send_json({"ok": safe_open(path)})
            return
        if parsed.path == "/api/asset":
            path = parse_qs(parsed.query).get("path", [""])[0]
            self.serve_asset(path)
            return
        # ==================== AGENT GET ENDPOINTS ====================
        if parsed.path == "/api/agent/alerts":
            # Return current alerts from autonomous agent
            try:
                from autonomous_agent import get_alerts
                alerts = get_alerts()
                self.send_json({
                    "alerts": alerts,
                    "count": len(alerts),
                    "timestamp": datetime.now().isoformat()
                })
            except Exception as exc:
                self.send_json({"alerts": [], "error": str(exc)}, 500)
            return
        if parsed.path == "/api/agent/recommendations":
            # Return recent recommendations from autonomous agent
            try:
                query_params = parse_qs(parsed.query)
                limit = int(query_params.get("limit", ["10"])[0])
                from autonomous_agent import get_recommendations
                recommendations = get_recommendations(limit=limit)
                self.send_json({
                    "recommendations": recommendations,
                    "count": len(recommendations),
                    "timestamp": datetime.now().isoformat()
                })
            except Exception as exc:
                self.send_json({"recommendations": [], "error": str(exc)}, 500)
            return
        if parsed.path == "/api/ab-testing/stats":
            # Return A/B testing statistics
            try:
                from ab_testing import get_stats
                stats = get_stats()
                self.send_json({
                    "stats": stats,
                    "timestamp": datetime.now().isoformat()
                })
            except Exception as exc:
                self.send_json({"stats": {}, "error": str(exc)}, 500)
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        global worker_thread
        if self.path == "/api/run":
            start_time = time.time()
            try:
                payload = self.read_body()
                if not payload.get("url"):
                    latency_ms = (time.time() - start_time) * 1000
                    log_event("api_call", {
                        "endpoint": "/api/run",
                        "method": "POST",
                        "latency_ms": latency_ms,
                        "status_code": 400,
                        "error": "Empty URL"
                    })
                    self.send_json({"ok": False, "error": "URL vazia"}, 400)
                    return
                ok, job_id = enqueue_payload(payload)
                latency_ms = (time.time() - start_time) * 1000

                if not ok:
                    log_event("api_call", {
                        "endpoint": "/api/run",
                        "method": "POST",
                        "latency_ms": latency_ms,
                        "status_code": 409,
                        "error": job_id
                    })
                    self.send_json({"ok": False, "error": job_id}, 409)
                    return

                # Log successful job submission
                log_event("api_call", {
                    "endpoint": "/api/run",
                    "method": "POST",
                    "latency_ms": latency_ms,
                    "status_code": 200,
                    "error": None
                })

                log_event("job_submitted", {
                    "job_id": job_id,
                    "url": payload.get("url"),
                    "priority": payload.get("priority", "normal"),
                    "clips_count": payload.get("count", 3),
                    "quality": payload.get("quality", "alta")
                })

                self.send_json({"ok": True, "job_id": job_id})
                return
            except Exception as e:
                latency_ms = (time.time() - start_time) * 1000
                error_msg = f"Erro interno: {str(e)}"
                print(f"[ERRO] /api/run: {error_msg}", file=sys.stderr)
                try:
                    self.send_json({"ok": False, "error": error_msg}, 500)
                except:
                    pass  # Conexão pode estar perdida
                return
        if self.path == "/api/batch":
            # Bulk submission: {urls: ["url1", "url2", ...], clips_count: 3, quality: "alta"}
            start_time = time.time()
            payload = self.read_body()
            urls = payload.get("urls", [])
            if not isinstance(urls, list) or not urls:
                latency_ms = (time.time() - start_time) * 1000
                log_event("api_call", {
                    "endpoint": "/api/batch",
                    "method": "POST",
                    "latency_ms": latency_ms,
                    "status_code": 400,
                    "error": "Empty or invalid URLs"
                })
                self.send_json({"ok": False, "error": "urls deve ser uma lista nao-vazia"}, 400)
                return
            job_ids = []
            errors = []
            for url in urls:
                url_str = str(url).strip()
                if url_str:
                    ok, result = enqueue_payload({
                        "url": url_str,
                        "count": payload.get("clips_count", 3),
                        "quality": payload.get("quality", "alta"),
                    })
                    if ok:
                        job_ids.append(result)
                    else:
                        errors.append(f"{url_str}: {result}")

            # Log successful batch submission
            latency_ms = (time.time() - start_time) * 1000
            log_event("api_call", {
                "endpoint": "/api/batch",
                "method": "POST",
                "latency_ms": latency_ms,
                "status_code": 200,
                "jobs_queued": len(job_ids),
                "total_urls": len(urls),
                "error": None
            })

            for job_id in job_ids:
                log_event("job_submitted", {
                    "job_id": job_id,
                    "priority": payload.get("priority", "normal"),
                    "clips_count": payload.get("clips_count", 3),
                    "quality": payload.get("quality", "alta")
                })

            self.send_json({
                "ok": len(job_ids) > 0,
                "job_ids": job_ids,
                "errors": errors,
                "queued": len(job_ids),
                "total": len(urls),
            })
            return
        if self.path == "/api/hook-variants":
            # Generate 3 hook variants for A/B testing
            # POST {transcript: "text..."} or {url: "youtube..."}
            start_time = time.time()
            payload = self.read_body()
            transcript = payload.get("transcript", "").strip()
            url = payload.get("url", "").strip()
            job_id = payload.get("job_id", "unknown")

            if not transcript and not url:
                latency_ms = (time.time() - start_time) * 1000
                log_event("api_call", {
                    "endpoint": "/api/hook-variants",
                    "method": "POST",
                    "latency_ms": latency_ms,
                    "status_code": 400,
                    "error": "No transcript or URL"
                })
                self.send_json({"ok": False, "error": "Forneça transcript ou url"}, 400)
                return

            # If URL provided, try to download and extract transcript
            if url and not transcript:
                try:
                    from find_viral_moments import download_subtitles, parse_vtt
                    subtitles = download_subtitles(url, "pt-orig,pt")
                    captions = parse_vtt(subtitles)
                    transcript = " ".join([c.get("text", "") for c in captions[:50]])  # First 50 captions
                except Exception as e:
                    latency_ms = (time.time() - start_time) * 1000
                    log_event("api_call", {
                        "endpoint": "/api/hook-variants",
                        "method": "POST",
                        "latency_ms": latency_ms,
                        "status_code": 400,
                        "error": f"Failed to extract transcript: {str(e)}"
                    })
                    self.send_json({"ok": False, "error": f"Erro ao extrair transcrição: {e}"}, 400)
                    return

            if not transcript:
                latency_ms = (time.time() - start_time) * 1000
                log_event("api_call", {
                    "endpoint": "/api/hook-variants",
                    "method": "POST",
                    "latency_ms": latency_ms,
                    "status_code": 400,
                    "error": "No transcript provided"
                })
                self.send_json({"ok": False, "error": "Nenhuma transcrição fornecida"}, 400)
                return

            # Generate variants
            try:
                work_dir = OUTPUTS / "hook-variants" / datetime.now().strftime("%Y%m%d%H%M%S")
                channel = payload.get("channel", "Poder em Jogo")
                gen_start = time.time()
                variants = generate_hook_variants(transcript, work_dir, channel_context=channel)
                gen_time = time.time() - gen_start

                # Log successful hook generation for each variant
                for variant in variants:
                    log_event("hook_generated", {
                        "job_id": job_id,
                        "style": variant.style,
                        "duration_s": variant.duration_s,
                        "success": True,
                        "fallback_to_heuristic": not variant.used_ai,
                        "generation_time_s": gen_time
                    })

                variants_data = [
                    {
                        "style": v.style,
                        "text": v.text,
                        "duration_s": v.duration_s,
                        "audio_url": f"/api/asset?path={v.audio_path}" if v.audio_path else None,
                        "used_ai": v.used_ai,
                    }
                    for v in variants
                ]

                latency_ms = (time.time() - start_time) * 1000
                log_event("api_call", {
                    "endpoint": "/api/hook-variants",
                    "method": "POST",
                    "latency_ms": latency_ms,
                    "status_code": 200,
                    "variants_generated": len(variants),
                    "error": None
                })

                self.send_json({
                    "ok": True,
                    "variants": variants_data,
                    "work_dir": str(work_dir),
                })
            except Exception as exc:
                latency_ms = (time.time() - start_time) * 1000
                log_event("api_call", {
                    "endpoint": "/api/hook-variants",
                    "method": "POST",
                    "latency_ms": latency_ms,
                    "status_code": 500,
                    "error": str(exc)
                })

                log_event("hook_generated", {
                    "job_id": job_id,
                    "success": False,
                    "error": str(exc)
                })

                self.send_json({"ok": False, "error": f"Erro ao gerar variantes: {exc}"}, 500)
            return
        if self.path == "/api/render":
            payload = self.read_body()
            rank = int(payload.get("rank", 0))
            preview = latest_candidates_path()
            if not rank or not preview:
                self.send_json({"ok": False}, 400)
                return
            cmd = [
                str(PYTHON),
                str(ROOT / "src" / "render_candidate.py"),
                "--candidate",
                str(rank),
                "--preview-json",
                str(preview),
                "--quality",
                str(payload.get("quality", "alta")),
                "--focus",
                str(payload.get("focus", "auto")),
            ]
            set_state(
                running=True,
                status="Renderizando",
                progress=76,
                stage=f"Renderizando candidato {rank}",
                render_duration=0.0,
                last_render_log_second=-1,
                log=[],
            )
            threading.Thread(target=render_async, args=(cmd, rank), daemon=True).start()
            self.send_json({"ok": True})
            return
        if self.path == "/api/candidate-preview":
            payload = self.read_body()
            rank = int(payload.get("rank", 0))
            if not rank:
                self.send_json({"ok": False, "error": "rank vazio"}, 400)
                return
            try:
                output = make_candidate_preview(rank)
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, 500)
                return
            self.send_json({"ok": True, "video": str(output)})
            return
        if self.path == "/api/tiktok":
            webbrowser.open("https://www.tiktok.com/tiktokstudio/upload")
            self.send_json({"ok": True})
            return
        if self.path == "/api/tiktok-setup":
            try:
                self.read_body()
            except Exception:
                pass
            try:
                py = str(PYTHON if PYTHON.exists() else Path(sys.executable))
                def run_setup(py=py) -> None:
                    try:
                        import importlib.util
                        if importlib.util.find_spec("playwright") is None:
                            append_log("[tiktok-setup] Instalando playwright...\n")
                            subprocess.run([py, "-m", "pip", "install", "playwright", "--quiet"], cwd=ROOT)
                            append_log("[tiktok-setup] Instalando navegador Chromium...\n")
                            subprocess.run([py, "-m", "playwright", "install", "chromium"], cwd=ROOT)
                    except Exception as exc:
                        append_log(f"[tiktok-setup] Erro na instalacao: {exc}\n")
                        return
                    append_log("[tiktok-setup] Abrindo navegador para login...\n")
                    subprocess.run([py, str(ROOT / "src" / "tiktok_uploader.py"), "--setup"], cwd=ROOT)
                    append_log("[tiktok-setup] Login salvo.\n")
                threading.Thread(target=run_setup, daemon=True).start()
                self.send_json({"ok": True})
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, 500)
            return
        if self.path == "/api/upload-tiktok":
            payload = self.read_body()
            folder_raw = str(payload.get("folder", "")).strip()
            title = str(payload.get("title", "")).strip()
            body_text = str(payload.get("body", "")).strip()
            tags = str(payload.get("tags", "")).strip()
            if not folder_raw:
                self.send_json({"ok": False, "error": "folder vazio"}, 400)
                return
            folder_path = Path(folder_raw)
            videos = sorted(folder_path.glob("*.mp4"), key=lambda p: p.stat().st_size, reverse=True)
            if not videos:
                self.send_json({"ok": False, "error": "Nenhum .mp4 encontrado na pasta"}, 404)
                return
            video_path = str(videos[0])
            py = str(PYTHON if PYTHON.exists() else Path(sys.executable))
            cmd = [py, str(ROOT / "src" / "tiktok_uploader.py"),
                   "--video", video_path,
                   "--title", title,
                   "--body", body_text,
                   "--tags", tags]
            def run_upload() -> None:
                append_log(f"[tiktok] Iniciando upload: {videos[0].name}\n")
                for line in subprocess.Popen(
                    cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace"
                ).stdout:
                    append_log(f"[tiktok] {line}")
            threading.Thread(target=run_upload, daemon=True).start()
            self.send_json({"ok": True, "video": videos[0].name})
            return
        if self.path == "/api/save-publication":
            payload = self.read_body()
            folder_raw = str(payload.get("folder", "")).strip()
            text = str(payload.get("text", "")).strip()
            if not folder_raw or not text:
                self.send_json({"ok": False, "error": "folder ou text vazio"}, 400)
                return
            folder = Path(folder_raw)
            try:
                resolved = folder.resolve()
            except Exception:
                self.send_json({"ok": False, "error": "pasta invalida"}, 400)
                return
            allowed = [ROOT.resolve(), OUTPUTS.resolve()]
            if not any(str(resolved).lower().startswith(str(base).lower()) for base in allowed):
                self.send_json({"ok": False, "error": "pasta nao permitida"}, 403)
                return
            pub_path = resolved / "publicacao.txt"
            pub_path.write_text(text + "\n", encoding="utf-8")
            self.send_json({"ok": True})
            return
        if self.path == "/api/analytics":
            payload = self.read_body()
            try:
                self.send_json(append_analytics_row(payload))
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, 400)
            return
        if self.path == "/api/radar/source":
            payload = self.read_body()
            value = str(payload.get("url", "")).strip()
            name = str(payload.get("name", "")).strip()
            auto_cut = bool(payload.get("auto_cut", False))
            content_type = str(payload.get("content_type", "podcast")).strip()
            if not value:
                self.send_json({"ok": False, "error": "Fonte vazia"}, 400)
                return
            try:
                source = add_source(value, name, auto_cut=auto_cut, content_type=content_type)
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, 500)
                return
            self.send_json({"ok": True, "source": source.__dict__})
            return
        if self.path == "/api/radar/scan":
            try:
                radar = scan_all()
                queued = enqueue_auto_radar_items(radar)
                self.send_json({"ok": True, "queued": queued, "radar": read_radar()})
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, 500)
            return
        if self.path == "/api/radar/process":
            payload = self.read_body()
            url = str(payload.get("url", "")).strip()
            video_id = str(payload.get("id", "")).strip()
            if not url:
                self.send_json({"ok": False, "error": "URL vazia"}, 400)
                return
            ok, error = enqueue_payload(
                {
                    "url": url,
                    "count": int(payload.get("count", 3)),
                    "min_score": int(payload.get("min_score", 75)),
                    "min_duration": int(payload.get("min_duration", 60)),
                    "max_duration": int(payload.get("max_duration", 90)),
                    "ai_mode": str(payload.get("ai_mode", "auto")),
                    "quality": str(payload.get("quality", "alta")),
                    "focus": "auto",
                }
            )
            if not ok:
                self.send_json({"ok": False, "error": error}, 409)
                return
            if video_id:
                mark_item(video_id, "na fila")
            self.send_json({"ok": True})
            return
        if self.path == "/api/radar/analyze":
            payload = self.read_body()
            url = str(payload.get("url", "")).strip()
            video_id = str(payload.get("id", "")).strip()
            if not url:
                self.send_json({"ok": False, "error": "URL vazia"}, 400)
                return
            ok, error = enqueue_payload(
                {
                    "url": url,
                    "count": int(payload.get("count", 10)),
                    "min_score": int(payload.get("min_score", 60)),
                    "min_duration": int(payload.get("min_duration", 45)),
                    "max_duration": int(payload.get("max_duration", 90)),
                    "ai_mode": str(payload.get("ai_mode", "auto")),
                    "quality": str(payload.get("quality", "alta")),
                    "focus": "auto",
                    "preview_only": True,
                }
            )
            if not ok:
                self.send_json({"ok": False, "error": error}, 409)
                return
            if video_id:
                mark_item(video_id, "analisando")
            self.send_json({"ok": True})
            return
        # ==================== AGENT ENDPOINTS ====================
        if self.path == "/api/skill/summarize-performance":
            # POST: Summarize system performance
            try:
                from mcp_skill_server import summarize_performance
                payload = self.read_body()
                days = int(payload.get("days", 7))
                result = summarize_performance(days=days)
                self.send_json(result)
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, 500)
            return
        if self.path == "/api/skill/diagnose":
            # POST: Diagnose system issues
            try:
                payload = self.read_body()
                from mcp_skill_server import diagnose_issue
                result = diagnose_issue(
                    error_message=payload.get("error_message", ""),
                    job_id=payload.get("job_id", "")
                )
                self.send_json(result)
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, 500)
            return
        if self.path == "/api/skill/optimize":
            # POST: Get audience optimization suggestions
            try:
                payload = self.read_body()
                from mcp_skill_server import optimize_for_audience
                result = optimize_for_audience(
                    audience_type=payload.get("audience_type", "general")
                )
                self.send_json(result)
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, 500)
            return
        if self.path == "/api/skill/analyze-competitor":
            # POST: Analyze competitor positioning
            try:
                payload = self.read_body()
                from mcp_skill_server import analyze_competitor
                result = analyze_competitor(
                    competitor_channel=payload.get("competitor_channel", "")
                )
                self.send_json(result)
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, 500)
            return
        self.send_response(404)
        self.end_headers()

    def serve_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self.send_response(404)
            self.end_headers()
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def serve_asset(self, path_value: str) -> None:
        path = Path(path_value)
        try:
            resolved = path.resolve()
        except Exception:
            self.send_response(404)
            self.end_headers()
            return
        allowed = [ROOT.resolve(), OUTPUTS.resolve()]
        if not any(str(resolved).lower().startswith(str(base).lower()) for base in allowed) or not resolved.exists():
            self.send_response(404)
            self.end_headers()
            return
        suffix = resolved.suffix.lower()
        content_type = "image/jpeg"
        if suffix == ".png":
            content_type = "image/png"
        elif suffix == ".webp":
            content_type = "image/webp"
        elif suffix == ".mp4":
            content_type = "video/mp4"
        elif suffix == ".webm":
            content_type = "video/webm"
        self.serve_media_file(resolved, content_type)

    def serve_media_file(self, path: Path, content_type: str) -> None:
        size = path.stat().st_size
        range_header = self.headers.get("Range")
        if range_header and range_header.startswith("bytes="):
            start_text, _, end_text = range_header.removeprefix("bytes=").partition("-")
            start = int(start_text or 0)
            end = int(end_text or size - 1)
            end = min(end, size - 1)
            length = end - start + 1
            self.send_response(206)
            self.send_header("Content-Type", content_type)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Length", str(length))
            self.end_headers()
            with path.open("rb") as file:
                file.seek(start)
                self.wfile.write(file.read(length))
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def get_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    try:
        ip = socket.gethostbyname(socket.gethostname())
        return "" if ip.startswith("127.") else ip
    except OSError:
        return ""


def main() -> None:
    global radar_thread
    WEB.mkdir(exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    local_url = f"http://127.0.0.1:{PORT}"
    lan_ip = get_lan_ip()
    lan_url = f"http://{lan_ip}:{PORT}" if lan_ip else ""
    print(f"Poder em Jogo Studio: {local_url}")
    if lan_url:
        print(f"iPhone/rede local: {lan_url}")
    radar_thread = threading.Thread(target=radar_monitor_loop, daemon=True)
    radar_thread.start()
    threading.Timer(0.5, lambda: webbrowser.open(local_url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
