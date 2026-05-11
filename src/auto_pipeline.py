from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from local_db import record_candidate_report, start_job, update_job


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
OUTPUTS = ROOT / "outputs"


def log(message: str) -> None:
    print(message, flush=True)


def run(cmd: list[str], allow_failure: bool = False) -> int:
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
        bufsize=1,
        env=env,
    )
    assert process.stdout
    for line in process.stdout:
        print(line, end="", flush=True)
    code = process.wait()
    if code != 0 and not allow_failure:
        raise RuntimeError(f"Comando falhou com codigo {code}: {' '.join(cmd)}")
    return code


def latest_candidates_json() -> Path:
    bases = [OUTPUTS / "relatorios" / "pre-aprovacao", OUTPUTS / "pre-aprovacao"]
    folders: list[Path] = []
    for base in bases:
        if base.exists():
            folders.extend([path for path in base.iterdir() if path.is_dir()])
    for folder in sorted(folders, key=lambda path: path.stat().st_mtime, reverse=True):
        data = folder / "candidatos.json"
        if data.exists():
            return data
    raise RuntimeError("Nao encontrei candidatos.json depois da analise.")


def choose_candidates(path: Path, count: int) -> tuple[dict, list[dict]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    candidates = data.get("candidates", [])
    ranked = sorted(
        candidates,
        key=lambda item: (
            str(item.get("decision", "")).upper() == "APROVAR",
            str(item.get("decision", "")).upper() == "TESTAR",
            int(item.get("score", 0)),
            int(item.get("channel_score", 0)),
        ),
        reverse=True,
    )
    approved_pool = [item for item in ranked if str(item.get("decision", "")).upper() != "REJEITAR"]
    selected = diversify_candidates(approved_pool, count)
    if len(selected) < count:
        selected.extend([item for item in diversify_candidates(ranked, count) if item not in selected])
    return data, selected


def timestamp_to_seconds(value: str) -> float:
    parts = str(value).split(":")
    if len(parts) != 3:
        return 0.0
    hours, minutes, seconds = parts
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def diversify_candidates(candidates: list[dict], count: int, min_gap_seconds: float = 180.0) -> list[dict]:
    selected: list[dict] = []
    for candidate in candidates:
        start = timestamp_to_seconds(str(candidate.get("start", "00:00:00")))
        if any(abs(start - timestamp_to_seconds(str(chosen.get("start", "00:00:00")))) < min_gap_seconds for chosen in selected):
            continue
        selected.append(candidate)
        if len(selected) >= count:
            return selected
    for candidate in candidates:
        if candidate not in selected:
            selected.append(candidate)
        if len(selected) >= count:
            break
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description="Fluxo automatico: analisa candidatos e renderiza os melhores cortes.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--min-score", type=int, default=75)
    parser.add_argument("--min-duration", type=int, default=60)
    parser.add_argument("--max-duration", type=int, default=90)
    parser.add_argument("--editorial-ai", choices=["auto", "off", "required"], default="auto")
    parser.add_argument("--quality", choices=["tiktok", "alta", "4k"], default="alta")
    parser.add_argument("--focus", choices=["auto", "left", "center", "right"], default="auto")
    parser.add_argument("--ai-model", default=None)
    parser.add_argument("--allow-low-quality", action="store_true")
    args = parser.parse_args()

    py = str(PYTHON if PYTHON.exists() else Path(sys.executable))
    job_id = start_job(args.url, count=args.count, min_score=args.min_score, quality=args.quality)
    try:
        log("AUTO 1/4 Analisando melhores candidatos")
        analyze_cmd = [
            py,
            str(ROOT / "src" / "analyze_candidates_fast.py"),
            "--url",
            args.url,
            "--count",
            str(max(10, args.count * 4)),
            "--min-score",
            str(max(55, args.min_score - 15)),
            "--min-duration",
            str(args.min_duration),
            "--max-duration",
            str(args.max_duration),
            "--editorial-ai",
            args.editorial_ai,
        ]
        if args.ai_model:
            analyze_cmd.extend(["--ai-model", args.ai_model])
        run(analyze_cmd)

        candidates_path = latest_candidates_json()
        data, selected = choose_candidates(candidates_path, args.count)
        record_candidate_report(args.url, candidates_path, len(data.get("candidates", [])))
        update_job(job_id, "selecionando", report=str(candidates_path), candidates=len(data.get("candidates", [])))
        if not selected:
            raise RuntimeError("A analise terminou, mas nenhum candidato ficou disponivel.")

        log(f"AUTO 2/4 Selecionados {len(selected)} candidatos")
        total = min(args.count, len(selected))
        rendered = 0
        rejected = 0
        for index, candidate in enumerate(selected, start=1):
            if rendered >= args.count:
                break
            rank = int(candidate.get("rank", index))
            log(f"AUTO 3/4 Renderizando candidato {rendered + 1}/{total} rank={rank} score={candidate.get('score')}")
            cmd = [
                py,
                str(ROOT / "src" / "render_candidate.py"),
                "--candidate",
                str(rank),
                "--preview-json",
                str(candidates_path),
                "--quality",
                args.quality,
                "--focus",
                args.focus,
                "--fail-on-rejected-quality",
            ]
            code = run(cmd, allow_failure=True)
            if code == 0:
                rendered += 1
                update_job(job_id, "renderizando", rendered=rendered, rejected=rejected, report=str(candidates_path))
                continue
            if code == 2:
                rejected += 1
                update_job(job_id, "renderizando", rendered=rendered, rejected=rejected, report=str(candidates_path))
                log(f"[auto] Candidato rank={rank} reprovado na qualidade. Pulando para o proximo.")
                continue
            raise RuntimeError(f"Render falhou com codigo {code} no candidato rank={rank}")

        if rendered <= 0:
            raise RuntimeError("Nenhum corte passou no controle de qualidade.")

        log("AUTO 4/4 Cortes prontos")
        update_job(job_id, "concluido", rendered=rendered, rejected=rejected, report=str(candidates_path))
    except Exception as exc:
        update_job(job_id, "erro", error=str(exc))
        raise


if __name__ == "__main__":
    main()
