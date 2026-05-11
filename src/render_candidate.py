from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

from create_cut_from_source import create_cut, slugify
from face_focus import analyze_face_focus, detect_face_focus
from local_db import record_cut
from quality_control import write_quality_report
from youtube_to_cut import download_youtube_section


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"


def write_user_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8-sig")


def discard_downloaded_source(path: Path) -> None:
    try:
        if path.exists() and path.is_file():
            path.unlink()
            print(f"Fonte temporaria removida: {path}")
    except OSError as exc:
        print(f"[aviso] Nao consegui remover fonte temporaria {path}: {exc}")


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def latest_preview_json() -> Path:
    bases = [OUTPUTS / "relatorios" / "pre-aprovacao", OUTPUTS / "pre-aprovacao"]
    folders: list[Path] = []
    for base in bases:
        if base.exists():
            folders.extend([path for path in base.iterdir() if path.is_dir()])
    if not folders:
        raise RuntimeError("Nenhum relatorio de pre-aprovacao encontrado. Rode primeiro com -PreviaApenas.")
    for folder in sorted(folders, key=lambda path: path.stat().st_mtime, reverse=True):
        candidate_file = folder / "candidatos.json"
        if candidate_file.exists():
            return candidate_file
    raise RuntimeError("Nao encontrei candidatos.json em outputs\\pre-aprovacao.")


def load_candidate(candidate_number: int, preview_json: Path | None = None) -> tuple[dict, dict, Path]:
    path = preview_json or latest_preview_json()
    data = json.loads(path.read_text(encoding="utf-8"))
    candidates = data.get("candidates", [])
    for candidate in candidates:
        if int(candidate.get("rank", 0)) == candidate_number:
            return data, candidate, path
    raise RuntimeError(f"Candidato {candidate_number} nao existe em {path}.")


def timestamp_to_seconds(value: str) -> float:
    parts = value.split(":")
    if len(parts) != 3:
        return 0.0
    hours, minutes, seconds = parts
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def write_score_file(out_dir: Path, source_url: str, candidate: dict, video_path: Path, focus: str, quality_result: dict | None = None) -> None:
    lines = [
        f"score={candidate.get('score', 0)}/100",
        f"classificacao={candidate.get('classification', '')}",
        f"inicio={candidate.get('start', '')}",
        f"duracao={candidate.get('duration', '')}",
        "pausas=pausas mantidas para preservar sincronia",
        f"headline={candidate.get('headline', '')}",
        f"gancho_inicial={candidate.get('hook_score', 0)}/100",
        f"motivo_gancho={candidate.get('hook_reason', '')}",
        f"score_editorial={candidate.get('editorial_score', 0)}/100",
        f"motivo_editorial={candidate.get('editorial_reason', '')}",
        f"foco={focus}",
        f"motivo={candidate.get('reason', '')}",
        f"fonte={source_url}",
        f"video={video_path}",
    ]
    if quality_result:
        lines.extend(
            [
                f"qualidade_status={quality_result.get('status')}",
                f"qualidade_score={quality_result.get('score')}/100",
                f"qualidade_resolucao={quality_result.get('width')}x{quality_result.get('height')}",
                f"qualidade_duracao={quality_result.get('duration')}s",
                f"qualidade_foco_rosto={quality_result.get('face_quality')}/100",
            ]
        )
        if quality_result.get("issues"):
            lines.append("qualidade_problemas=" + "; ".join(quality_result.get("issues", [])))
        if quality_result.get("warnings"):
            lines.append("qualidade_avisos=" + "; ".join(quality_result.get("warnings", [])))
    write_user_text(out_dir / "score-viral.txt", "\n".join(lines) + "\n")


def write_posting_pack(video_path: Path, source_dir: Path, candidate: dict, source_url: str) -> Path:
    pack_dir = OUTPUTS / "_postar_agora" / datetime.now().strftime("%Y%m%d-%H%M%S")
    pack_dir.mkdir(parents=True, exist_ok=True)

    target_video = pack_dir / f"01-publicar-agora-{slugify(candidate.get('headline', 'corte'))}{video_path.suffix}"
    shutil.copy2(video_path, target_video)

    for sidecar in ["publicacao.txt", "score-viral.txt", "qualidade.txt", "qualidade.json"]:
        sidecar_path = source_dir / sidecar
        if sidecar_path.exists():
            shutil.copy2(sidecar_path, pack_dir / sidecar)

    readme = [
        "# Pacote para postar agora\n\n",
        f"Fonte: {source_url}\n\n",
        f"Candidato: {candidate.get('rank')}\n",
        f"Score: {candidate.get('score')}/100 - {candidate.get('classification')}\n",
        f"Inicio: {candidate.get('start')} | Duracao: {candidate.get('duration')}s\n\n",
        "Video recomendado:\n",
        f"{target_video}\n\n",
        "Legenda e hashtags:\n",
        "Abra `publicacao.txt`.\n",
    ]
    write_user_text(pack_dir / "LEIA-ME.txt", "".join(readme))
    return pack_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Renderiza um candidato escolhido no relatorio de pre-aprovacao.")
    parser.add_argument("--candidate", type=int, required=True, help="Numero do candidato no relatorio.")
    parser.add_argument("--preview-json", default=None, help="Caminho opcional para candidatos.json.")
    parser.add_argument("--quality", choices=["tiktok", "alta", "4k"], default="alta")
    parser.add_argument("--focus", choices=["auto", "left", "center", "right"], default="auto")
    parser.add_argument("--show-hook", action="store_true", help="Mostra gancho visual nos primeiros 5s. Padrao: desligado.")
    parser.add_argument("--fail-on-rejected-quality", action="store_true", help="Retorna erro se o controle de qualidade reprovar.")
    args = parser.parse_args()

    data, candidate, preview_path = load_candidate(args.candidate, Path(args.preview_json) if args.preview_json else None)
    source_video_raw = str(data.get("source_video", "")).strip()
    source_video = Path(source_video_raw) if source_video_raw else None
    source_url = data.get("source", "")
    downloaded_for_render = False
    if source_video is None or not source_video.exists() or source_video.is_dir():
        if not source_url:
            raise FileNotFoundError(source_video_raw or "source_video vazio")
        print("Video-fonte nao estava salvo. Baixando apenas o trecho deste candidato...")
        source_video = download_youtube_section(source_url, str(candidate["start"]), float(candidate["duration"]))
        downloaded_for_render = True

    start = str(candidate["start"])
    duration = float(candidate["duration"])
    render_start = "00:00:00" if downloaded_for_render else start
    focus_start = 0.0 if downloaded_for_render else timestamp_to_seconds(start)
    headline = str(candidate["headline"])
    focus = args.focus
    focus_timeline = None
    focus_quality = None
    if focus == "auto":
        focus = detect_face_focus(source_video, focus_start, duration)
        focus_analysis = analyze_face_focus(source_video, focus_start, duration)
        focus_timeline = [
            (float(segment.start), float(segment.end), float(segment.x), float(segment.y))
            for segment in focus_analysis.segments
        ]
        focus_quality = focus_analysis.quality_score

    print(f"Renderizando candidato {candidate['rank']} do relatorio:")
    print(preview_path)
    timeline_note = f" | Foco dinamico: {len(focus_timeline)} segmentos" if focus_timeline else ""
    quality_note = f" | Qualidade visual: {focus_quality}/100" if focus_quality is not None else ""
    print(f"Inicio: {start} | Duracao: {int(duration)}s | Score: {candidate.get('score')}/100 | Foco: {focus}{timeline_note}{quality_note}")

    video_path = create_cut(
        source_video,
        render_start,
        duration,
        headline,
        show_headline=False,
        quality=args.quality,
        hook=headline,
        show_hook=args.show_hook,
        focus=focus,
        motion_style="standard",
        variant_name="escolhido",
        focus_timeline=focus_timeline,
    )

    out_dir = video_path.parent
    print("Controle de qualidade automatico...")
    quality_result = write_quality_report(video_path, expected_duration=duration, quality=args.quality)
    print(f"Qualidade: {quality_result['status']} ({quality_result['score']}/100)")
    for issue in quality_result.get("issues", []):
        print(f"[qualidade] problema: {issue}")
    for warning in quality_result.get("warnings", []):
        print(f"[qualidade] aviso: {warning}")

    write_user_text(out_dir / "publicacao.txt", str(candidate.get("publication", "")).strip() + "\n")
    write_score_file(out_dir, source_url, candidate, video_path, focus, quality_result)
    pack = None
    if quality_result["status"] != "reprovado":
        pack = write_posting_pack(video_path, out_dir, candidate, source_url)

    print(f"Corte criado: {video_path}")
    if pack:
        print(f"Postar agora: {pack}")
    else:
        print("Postar agora: nao criado porque o controle de qualidade reprovou o corte.")
    record_cut(source_url, candidate, video_path, pack, quality_result)
    if downloaded_for_render:
        discard_downloaded_source(source_video)
    if args.fail_on_rejected_quality and quality_result["status"] == "reprovado":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
