from __future__ import annotations

import argparse
import atexit
import html
import json
import re
import shutil
import subprocess
import sys
import textwrap
from datetime import datetime, timedelta
from pathlib import Path

from channel_profile import angle_copy, load_channel_profile
from create_cut_from_source import create_cut, ffmpeg_path, slugify
from editorial_judge import judge_candidates, local_editorial_score
from face_focus import analyze_face_focus, detect_face_focus
from find_viral_moments import (
    CaptionLine,
    approval_decision,
    build_media_signals,
    classify_score,
    download_subtitles,
    find_candidates,
    first_sentence,
    parse_vtt,
    seconds_to_timestamp,
)
from make_best_cut import clean_headline
from quality_control import write_quality_report
from silence_cutter import cut_silences
from tiktok_learning import learned_score
from video_probe import probe_video
from youtube_to_cut import download_youtube


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
WEAK_ENDING_WORDS = {
    "a",
    "o",
    "as",
    "os",
    "um",
    "uma",
    "de",
    "da",
    "do",
    "das",
    "dos",
    "em",
    "no",
    "na",
    "nos",
    "nas",
    "para",
    "pra",
    "por",
    "com",
    "como",
    "que",
    "porque",
    "e",
}


def discard_downloaded_source(path: Path) -> None:
    try:
        if path.exists() and path.is_file():
            path.unlink()
            print(f"Fonte temporaria removida: {path}")
    except OSError as exc:
        print(f"[aviso] Nao consegui remover fonte temporaria {path}: {exc}")


def write_user_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8-sig")


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def score_label(score: int) -> str:
    if score >= 85:
        return "muito-alto"
    if score >= 70:
        return "alto"
    if score >= 55:
        return "medio"
    if score >= 40:
        return "baixo"
    return "ruim"


def hook_from_headline(headline: str) -> str:
    headline = clean_headline(headline).strip()
    if len(headline) > 52:
        headline = headline[:52].rsplit(" ", 1)[0]
    return headline or "PRESTA ATENCAO NESSE TRECHO"


def suggested_publish_time(rank: int) -> str:
    slots = [(12, 30), (19, 30)]
    now = datetime.now()
    minimum = now + timedelta(hours=2)
    cursor = now.replace(hour=slots[0][0], minute=slots[0][1], second=0, microsecond=0)
    if cursor <= minimum:
        cursor = now.replace(hour=slots[1][0], minute=slots[1][1], second=0, microsecond=0)
    if cursor <= minimum:
        tomorrow = now + timedelta(days=1)
        cursor = tomorrow.replace(hour=slots[0][0], minute=slots[0][1], second=0, microsecond=0)

    extra_slots = rank - 1
    for _ in range(extra_slots):
        if cursor.hour == 12:
            cursor = cursor.replace(hour=19, minute=30)
        else:
            next_day = cursor + timedelta(days=1)
            cursor = next_day.replace(hour=12, minute=30)
    return cursor.strftime("%d/%m/%Y %H:%M")


def normalize_for_copy(text: str) -> str:
    text = html.unescape(text or "")
    text = fix_mojibake(text)
    text = re.sub(r"(?:^|\s)>>+", " ", text)
    text = re.sub(r"\[[^\]]+\]", " ", text)
    text = clean_headline(text).strip()
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .,:;")


def fix_mojibake(text: str) -> str:
    if not text:
        return ""
    try:
        fixed = text.encode("latin1").decode("utf-8")
        if fixed.count("Ã") + fixed.count("Â") < text.count("Ã") + text.count("Â"):
            return fixed
    except UnicodeError:
        pass
    replacements = {
        "Ã¡": "á",
        "Ã ": "à",
        "Ã¢": "â",
        "Ã£": "ã",
        "Ã©": "é",
        "Ãª": "ê",
        "Ã­": "í",
        "Ã³": "ó",
        "Ã´": "ô",
        "Ãµ": "õ",
        "Ãº": "ú",
        "Ã§": "ç",
        "Ã‰": "É",
        "Ã‡": "Ç",
        "Â": "",
    }
    for broken, fixed in replacements.items():
        text = text.replace(broken, fixed)
    return text


def is_bad_copy_candidate(text: str) -> bool:
    lower = text.lower().strip()
    if not lower or len(lower.split()) < 5:
        return True
    bad_fragments = [
        ">>",
        "&gt;",
        "nenhuma nenhuma",
        "só que desta vez",
        "so que desta vez",
        "né né",
        "tipo assim",
    ]
    if any(fragment in lower for fragment in bad_fragments):
        return True
    filler_starts = (
        "e ",
        "é ",
        "né ",
        "então ",
        "cara ",
        "tipo ",
        "só que ",
        "so que ",
    )
    return lower.startswith(filler_starts)


def polish_copy_hook(text: str) -> str:
    text = normalize_for_copy(text)
    text = re.sub(r"^(deles|dele|dela|eles|elas|isso|aquilo),?\s+(porque|que)\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^(porque|que)\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r",?\s+n[ée]\??$", "", text, flags=re.IGNORECASE)
    letters = [char for char in text if char.isalpha()]
    if letters and sum(char.isupper() for char in letters) / len(letters) > 0.65:
        text = text.lower()
        text = text[:1].upper() + text[1:]
    words = text.split()
    while len(words) > 5 and words[-1].lower().strip(".,;:!?") in WEAK_ENDING_WORDS:
        words.pop()
    text = " ".join(words)
    return text.strip(" .,:;")


def contains_term(text: str, term: str) -> bool:
    if " " in term:
        return term in text
    return re.search(rf"(?<![a-zA-Z0-9_]){re.escape(term)}(?![a-zA-Z0-9_])", text) is not None


def detect_publication_angle(headline: str, transcript: str = "") -> tuple[str, list[str], str]:
    combined = normalize_for_copy(f"{headline} {transcript}").lower()
    themes = {
        "ia": ["ia", "inteligencia artificial", "inteligência artificial", "chatgpt", "tecnologia", "empresa", "negocio", "negócio"],
        "geopolitica": ["china", "eua", "russia", "rússia", "europa", "otan", "guerra", "estado", "politica", "política", "poder"],
        "economia": ["dinheiro", "dolar", "dólar", "ouro", "petroleo", "petróleo", "energia", "mercado", "bilhoes", "bilhões", "trilhoes", "trilhões", "produtividade", "inflacao", "inflação"],
        "carreira": ["homem", "disciplina", "trabalho", "sucesso", "mentalidade", "empresa", "empreendedor"],
    }
    for name, needles in themes.items():
        if any(contains_term(combined, term) for term in needles):
            if name == "ia":
                return (
                    "negocios",
                    ["#ia", "#negocios", "#empreendedorismo", "#tecnologia", "#poderemjogo"],
                    "Você acha que a maioria das empresas vai acordar tarde?",
                )
            if name == "economia":
                return (
                    "economia",
                    ["#economia", "#geopolitica", "#mercado", "#poder", "#poderemjogo"],
                    "Quem ganha poder quando esse movimento acontece?",
                )
            if name == "carreira":
                return (
                    "carreira",
                    ["#mentalidade", "#empreendedorismo", "#cortes", "#disciplina", "#poderemjogo"],
                    "Você concorda ou acha exagero?",
                )
            return (
                "geopolitica",
                ["#geopolitica", "#politica", "#historia", "#poder", "#poderemjogo"],
                "Você acha que isso foi estratégia ou erro?",
            )
    return (
        "geral",
        ["#geopolitica", "#politica", "#historia", "#cortes", "#poderemjogo"],
        "Esse detalhe muda sua leitura do assunto?",
    )


def detect_publication_angle(headline: str, transcript: str = "") -> tuple[str, list[str], str]:
    combined = normalize_for_copy(f"{headline} {transcript}").lower()
    themes = {
        "negocios": [
            "ia",
            "inteligencia artificial",
            "inteligência artificial",
            "chatgpt",
            "tecnologia",
            "empresa",
            "negocio",
            "negócio",
            "startup",
            "gestao",
            "gestão",
        ],
        "economia": [
            "dinheiro",
            "dolar",
            "dólar",
            "ouro",
            "petroleo",
            "petróleo",
            "energia",
            "mercado",
            "bilhoes",
            "bilhões",
            "trilhoes",
            "trilhões",
            "produtividade",
            "inflacao",
            "inflação",
        ],
        "geopolitica": [
            "china",
            "eua",
            "russia",
            "rússia",
            "europa",
            "otan",
            "guerra",
            "estado",
            "politica",
            "política",
            "poder",
        ],
        "carreira": ["homem", "disciplina", "trabalho", "sucesso", "mentalidade", "empreendedor"],
    }
    profile = load_channel_profile()
    for angle, needles in themes.items():
        if any(contains_term(combined, term) for term in needles):
            copy = angle_copy(angle)
            return (
                angle,
                copy.get("hashtags", profile.get("default_hashtags", [])),
                copy.get("question", "Esse detalhe muda sua leitura do assunto?"),
            )
    copy = angle_copy("geral")
    return (
        "geral",
        copy.get("hashtags", profile.get("default_hashtags", [])),
        copy.get("question", "Esse detalhe muda sua leitura do assunto?"),
    )


def extract_copy_hook(headline: str, transcript: str = "") -> str:
    clean = normalize_for_copy(headline)
    transcript = normalize_for_copy(transcript)
    candidates = []
    if clean and not is_bad_copy_candidate(clean):
        candidates.append(clean)
    for sentence in re.split(r"(?<=[.!?])\s+|(?<=,)\s+", transcript):
        sentence = normalize_for_copy(sentence)
        if 28 <= len(sentence) <= 115 and not is_bad_copy_candidate(sentence):
            candidates.append(sentence)

    strong_terms = [
        "problema",
        "verdade",
        "erro",
        "risco",
        "dinheiro",
        "poder",
        "empresa",
        "china",
        "eua",
        "guerra",
        "ninguém",
        "ninguem",
        "na verdade",
        "só que",
        "so que",
    ]
    fallback = clean if clean else "Esse detalhe muda o jogo"
    chosen = max(
        candidates or [fallback],
        key=lambda item: (
            sum(term in item.lower() for term in strong_terms),
            "?" in item,
            -abs(len(item) - 72),
        ),
    )
    chosen = polish_copy_hook(chosen)
    if len(chosen) > 105:
        chosen = chosen[:105].rsplit(" ", 1)[0]
    return chosen


def publication_text(headline: str, rank: int, transcript: str = "", score: int | None = None) -> str:
    clean = normalize_for_copy(headline).rstrip(".")
    hook = extract_copy_hook(clean, transcript)
    angle, hashtags, question = detect_publication_angle(clean, transcript)
    support_line = angle_copy(angle).get("support", "O detalhe parece pequeno, mas muda a leitura do jogo.")
    caption = (
        f"{hook}.\n\n"
        f"{support_line}\n\n"
        f"{question}"
    )

    schedule = suggested_publish_time(rank)
    return (
        caption
        + "\n\n"
        + " ".join(hashtags[:5])
        + "\n\n"
        + f"Horario sugerido: {schedule}\n"
    )


def srt_timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    whole = int(seconds)
    millis = int(round((seconds - whole) * 1000))
    hours = whole // 3600
    minutes = (whole % 3600) // 60
    secs = whole % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def short_subtitle(text: str) -> str:
    words = text.strip().split()
    if len(words) > 12:
        text = " ".join(words[:12])
    return "\n".join(textwrap.wrap(text, width=28, break_long_words=False)[:2])


def write_cut_subtitles(captions: list[CaptionLine], start: float, end: float, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    srt_path = out_dir / "legendas.srt"
    lines: list[str] = []
    index = 1
    for caption in captions:
        if caption.end <= start or caption.start >= end:
            continue
        relative_start = max(0.0, caption.start - start)
        relative_end = min(end - start, caption.end - start)
        if relative_end - relative_start < 0.25:
            continue
        text = short_subtitle(caption.text)
        if not text:
            continue
        lines.extend(
            [
                str(index),
                f"{srt_timestamp(relative_start)} --> {srt_timestamp(relative_end)}",
                text,
                "",
            ]
        )
        index += 1
    write_user_text(srt_path, "\n".join(lines))
    return srt_path


def write_index(created: list[dict], source: str) -> Path:
    out_dir = OUTPUTS / "relatorios" / "opus-local"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "ultimos-cortes.json"
    md_path = out_dir / "ultimos-cortes.md"

    json_path.write_text(json.dumps({"source": source, "cuts": created}, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [f"# Cortes gerados\n\nFonte: {source}\n\n"]
    for item in created:
        lines.extend(
            [
                f"## {item['rank']}. Score {item['score']}/100 - {item['classification']}\n\n",
                f"Arquivo: `{item['video']}`\n\n",
                "Variacoes:\n"
                + "".join(f"- {variant['variant']}: `{variant['video']}`\n" for variant in item.get("variants", []))
                + "\n",
                f"Decisao: {item.get('decision', '')}\n\n",
                f"Inicio: {item['start']} | Duracao original: {item['duration']}s | Duracao final: {item.get('render_duration', item['duration'])}s | Foco: {item['focus']}\n\n",
                f"Ajuste de entrada: {item.get('start_adjustment', 0):+.1f}s\n\n",
                f"Ritmo: {item.get('pause_note', '')}\n\n",
                "Validacao: "
                + "; ".join(
                    (
                        f"{variant['variant']}={'OK' if variant.get('validation', {}).get('ok') else 'PROBLEMA'}"
                        f" visual={variant.get('validation', {}).get('visual', {}).get('score', 0)}/100"
                    )
                    for variant in item.get("variants", [])
                )
                + "\n\n",
                f"Gancho inicial: {item.get('hook_score', 0)}/100 - {item.get('hook_reason', '')}\n\n",
                f"Headline: {item['headline']}\n\n",
                f"Score editorial: {item.get('editorial_score', 0)}/100 - {item.get('editorial_reason', '')}\n\n",
                f"Publicacao sugerida: {item['publish_time']}\n\n",
                f"Motivo: {item['reason']}\n\n",
            ]
        )
    write_user_text(md_path, "".join(lines))
    return md_path


def write_posting_pack(created: list[dict], source: str) -> Path:
    pack_dir = OUTPUTS / "relatorios" / "postagem" / datetime.now().strftime("%Y%m%d-%H%M%S")
    pack_dir.mkdir(parents=True, exist_ok=True)

    if not created:
        return pack_dir

    best = sorted(
        created,
        key=lambda item: (item.get("score", 0), item.get("editorial_score", 0)),
        reverse=True,
    )[0]
    variants = best.get("variants", [])
    preferred = next((item for item in variants if item.get("variant") == "limpa"), variants[0] if variants else None)

    recommended_video = ""
    if preferred:
        source_video = Path(preferred["video"])
        recommended_video = str(source_video)

        source_folder = source_video.parent
        for sidecar in ["publicacao.txt", "score-viral.txt", "qualidade.txt", "qualidade.json"]:
            sidecar_path = source_folder / sidecar
            if sidecar_path.exists():
                shutil.copy2(sidecar_path, pack_dir / sidecar)

    readme = [
        "# Pacote para postar agora\n\n",
        f"Fonte: {source}\n\n",
        f"Score: {best['score']}/100 - {best['classification']}\n",
        f"Gancho inicial: {best.get('hook_score', 0)}/100 - {best.get('hook_reason', '')}\n",
        f"Ajuste de entrada: {best.get('start_adjustment', 0):+.1f}s\n",
        f"Score editorial: {best.get('editorial_score', 0)}/100\n",
        f"Horario sugerido: {best['publish_time']}\n\n",
        "Video recomendado:\n",
        f"{recommended_video or 'Nenhum video aprovado'}\n\n",
        "Outras variacoes:\n",
        "".join(f"- {variant['variant']}: {variant['video']}\n" for variant in variants),
        "\n",
        "Legenda e hashtags:\n",
        "Abra `publicacao.txt`.\n\n",
        "Observacao:\n",
        "A versao limpa e a recomendada para postar primeiro. Este pacote nao duplica o video; ele aponta para a pasta aprovada.\n",
    ]
    write_user_text(pack_dir / "LEIA-ME.txt", "".join(readme))
    return pack_dir


def preview_frame(source: Path, start_seconds: float, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    timestamp = seconds_to_timestamp(start_seconds + 0.7)
    subprocess.run(
        [
            ffmpeg_path(),
            "-y",
            "-ss",
            timestamp,
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-vf",
            "scale=540:960:force_original_aspect_ratio=increase,crop=540:960",
            "-q:v",
            "2",
            str(output),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def decision_priority(decision: str) -> int:
    priorities = {"APROVAR": 3, "TESTAR": 2, "REJEITAR": 1}
    return priorities.get(decision.upper(), 0)


def candidate_decision(candidate) -> str:
    return approval_decision(candidate.score, candidate.hook_score, candidate.reason)


def candidates_for_render(candidates: list, minimum_decision: str) -> list:
    minimum = decision_priority(minimum_decision)
    return [candidate for candidate in candidates if decision_priority(candidate_decision(candidate)) >= minimum]


def clamp_float(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def base_focus_timeline(focus_timeline: list | None, focus: str, duration: float) -> list[tuple[float, float, float, float]]:
    if focus_timeline:
        normalized = []
        for segment in focus_timeline:
            start, end, x_pos, *rest = segment
            y_pos = rest[0] if rest else 0.42
            normalized.append((float(start), float(end), float(x_pos), float(y_pos)))
        return normalized
    focus_positions = {"left": 0.24, "center": 0.50, "right": 0.76}
    return [(0.0, float(duration), focus_positions.get(focus, 0.50), 0.42)]


def shifted_focus_timeline(focus_timeline: list | None, focus: str, duration: float, offset: float) -> list[tuple[float, float, float, float]]:
    return [
        (start, end, clamp_float(x_pos + offset, 0.14, 0.86), y_pos)
        for start, end, x_pos, y_pos in base_focus_timeline(focus_timeline, focus, duration)
    ]


def next_focus_offset(current_offset: float, validation: dict) -> float:
    visual = validation.get("visual", {})
    avg_center_x = float(visual.get("avg_center_x", 0.5))
    error = avg_center_x - 0.5
    if abs(error) < 0.01:
        return current_offset
    return clamp_float(current_offset + error * 0.42, -0.16, 0.16)


def focus_offset_for_attempt(attempt: int, current_offset: float, validation: dict) -> float | None:
    if attempt == 0:
        return 0.0
    visual = validation.get("visual", {})
    avg_center_x = float(visual.get("avg_center_x", 0.5))
    error = avg_center_x - 0.5
    if abs(error) >= 0.04:
        return next_focus_offset(current_offset, validation)
    alternates = [0.05, -0.05, 0.09, -0.09]
    index = attempt - 1
    if index < len(alternates):
        return alternates[index]
    return None


def validate_rendered_cut(path: Path, expected_duration: float, min_width: int = 1000, min_height: int = 1700) -> dict:
    info = probe_video(path)
    issues: list[str] = []
    if not path.exists() or path.stat().st_size < 500_000:
        issues.append("arquivo muito pequeno")
    if not info.has_audio:
        issues.append("sem audio")
    if info.width < min_width or info.height < min_height:
        issues.append(f"resolucao baixa: {info.width}x{info.height}")
    if info.duration and abs(info.duration - expected_duration) > 0.75:
        issues.append(f"duracao inesperada: {info.duration:.2f}s vs {expected_duration:.2f}s")
    visual = validate_face_centering(path)
    if not visual["ok"]:
        issues.extend(visual["issues"])
    return {
        "ok": not issues,
        "issues": issues,
        "width": info.width,
        "height": info.height,
        "duration": info.duration,
        "has_audio": info.has_audio,
        "bitrate": info.bitrate,
        "visual": visual,
    }


def validate_face_centering(path: Path, samples_per_second: float = 0.55) -> dict:
    try:
        import cv2
    except Exception:
        return {
            "ok": False,
            "score": 0,
            "issues": ["OpenCV indisponivel para validar rosto"],
            "coverage": 0.0,
            "avg_x_error": 1.0,
            "avg_y_error": 1.0,
            "offcenter_rate": 1.0,
            "avg_face_area": 0.0,
            "samples": 0,
            "detected": 0,
        }

    cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    detector = cv2.CascadeClassifier(str(cascade_path))
    if detector.empty():
        return {
            "ok": False,
            "score": 0,
            "issues": ["detector de rosto indisponivel"],
            "coverage": 0.0,
            "avg_x_error": 1.0,
            "avg_y_error": 1.0,
            "offcenter_rate": 1.0,
            "avg_face_area": 0.0,
            "samples": 0,
            "detected": 0,
        }

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return {
            "ok": False,
            "score": 0,
            "issues": ["nao abriu video para validar rosto"],
            "coverage": 0.0,
            "avg_x_error": 1.0,
            "avg_y_error": 1.0,
            "offcenter_rate": 1.0,
            "avg_face_area": 0.0,
            "samples": 0,
            "detected": 0,
        }

    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    duration = frame_count / fps if frame_count else 0
    sample_count = max(8, min(36, int(max(duration, 1) * samples_per_second)))
    x_errors: list[float] = []
    y_errors: list[float] = []
    centers_x: list[float] = []
    centers_y: list[float] = []
    face_areas: list[float] = []
    offcenter = 0
    detected = 0

    for index in range(sample_count):
        relative = (index + 0.5) / sample_count
        frame_number = int(relative * max(frame_count - 1, 0))
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ok, frame = cap.read()
        if not ok:
            continue
        height, width = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = detector.detectMultiScale(gray, scaleFactor=1.08, minNeighbors=4, minSize=(72, 72))
        if len(faces) == 0:
            continue
        x, y, w, h = max(faces, key=lambda item: item[2] * item[3])
        detected += 1
        center_x = (x + w / 2) / max(width, 1)
        center_y = (y + h / 2) / max(height, 1)
        centers_x.append(float(center_x))
        centers_y.append(float(center_y))
        x_error = abs(center_x - 0.50)
        y_error = abs(center_y - 0.48)
        x_errors.append(float(x_error))
        y_errors.append(float(y_error))
        face_areas.append(float(w * h) / max(float(width * height), 1.0))
        if x_error > 0.16 or y_error > 0.23:
            offcenter += 1

    cap.release()

    coverage = detected / max(sample_count, 1)
    avg_x_error = sum(x_errors) / max(len(x_errors), 1)
    avg_y_error = sum(y_errors) / max(len(y_errors), 1)
    avg_center_x = sum(centers_x) / max(len(centers_x), 1)
    avg_center_y = sum(centers_y) / max(len(centers_y), 1)
    avg_face_area = sum(face_areas) / max(len(face_areas), 1)
    offcenter_rate = offcenter / max(detected, 1)

    score = 100
    issues: list[str] = []
    if coverage < 0.35:
        score -= 55
        issues.append("rosto pouco detectado no video final")
    elif coverage < 0.60:
        score -= 25
        issues.append("rosto intermitente no video final")

    if avg_x_error > 0.18:
        score -= 35
        issues.append(f"rosto fora do centro horizontal: erro medio {avg_x_error:.2f}")
    elif avg_x_error > 0.11:
        score -= 15
        issues.append(f"rosto levemente fora do centro horizontal: erro medio {avg_x_error:.2f}")

    if avg_y_error > 0.26:
        score -= 24
        issues.append(f"rosto fora do centro vertical: erro medio {avg_y_error:.2f}")
    elif avg_y_error > 0.18:
        score -= 10
        issues.append(f"rosto levemente fora do centro vertical: erro medio {avg_y_error:.2f}")

    if offcenter_rate > 0.35:
        score -= 18
        issues.append(f"rosto descentralizado em {offcenter_rate:.0%} das amostras")

    if avg_face_area < 0.012:
        score -= 14
        issues.append("rosto pequeno no video final")

    score = max(0, min(100, score))
    return {
        "ok": score >= 65 and coverage >= 0.35 and avg_x_error <= 0.18 and offcenter_rate <= 0.65,
        "score": score,
        "issues": issues,
        "coverage": round(coverage, 3),
        "avg_center_x": round(avg_center_x, 3),
        "avg_center_y": round(avg_center_y, 3),
        "avg_x_error": round(avg_x_error, 3),
        "avg_y_error": round(avg_y_error, 3),
        "offcenter_rate": round(offcenter_rate, 3),
        "avg_face_area": round(avg_face_area, 5),
        "samples": sample_count,
        "detected": detected,
    }


def write_rejected_report(candidates: list, source_url: str) -> Path:
    rejected = [candidate for candidate in candidates if candidate_decision(candidate) == "REJEITAR"]
    out_dir = OUTPUTS / "rejeitados"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-rejeitados.md"
    lines = [f"# Cortes rejeitados\n\nFonte: {source_url}\n\n"]
    if not rejected:
        lines.append("Nenhum candidato rejeitado nesta rodada.\n")
    for rank, candidate in enumerate(rejected, start=1):
        lines.extend(
            [
                f"## {rank}. {clean_headline(candidate.headline)}\n\n",
                f"Score: {candidate.score}/100 | Gancho: {candidate.hook_score}/100\n\n",
                f"Inicio: `{seconds_to_timestamp(candidate.start)}` | Duracao: `{int(candidate.end - candidate.start)}s`\n\n",
                f"Primeira frase: {first_sentence(candidate.text)}\n\n",
                f"Motivo: {candidate.reason}\n\n",
            ]
        )
    write_user_text(path, "".join(lines))
    return path


def write_candidate_preview_report(candidates: list, source_video: Path | None, source_url: str) -> Path:
    preview_dir = OUTPUTS / "relatorios" / "pre-aprovacao" / datetime.now().strftime("%Y%m%d-%H%M%S")
    preview_dir.mkdir(parents=True, exist_ok=True)
    report_path = preview_dir / "relatorio-de-aprovacao.md"
    data_path = preview_dir / "candidatos.json"

    data = {
        "source": source_url,
        "source_video": str(source_video) if source_video else "",
        "candidates": [],
    }
    lines = [
        "# Relatorio de aprovacao dos cortes\n\n",
        f"Fonte: {source_url}\n\n",
        f"Video local: `{source_video if source_video else 'sera baixado apenas na renderizacao'}`\n\n",
        "Use este relatorio para escolher qual corte vale renderizar/postar.\n\n",
    ]

    for rank, candidate in enumerate(candidates, start=1):
        start = seconds_to_timestamp(candidate.start)
        duration = int(candidate.end - candidate.start)
        headline = clean_headline(candidate.headline)
        frame_path = preview_dir / f"{rank:02d}-{slugify(headline)}.jpg"
        if source_video:
            try:
                preview_frame(source_video, candidate.start, frame_path)
                frame_note = f"![frame inicial]({frame_path.name})"
            except Exception as exc:
                frame_note = f"Frame inicial nao gerado: {exc}"
        else:
            frame_note = "Frame inicial sera gerado apenas depois da renderizacao."

        publish_copy = publication_text(headline, rank, candidate.text, candidate.score)
        preview_text = candidate.text[:900].strip()
        item = {
            "rank": rank,
            "score": candidate.score,
            "classification": score_label(candidate.score),
            "decision": candidate_decision(candidate),
            "start": start,
            "duration": duration,
            "headline": headline,
            "first_sentence": first_sentence(candidate.text),
            "hook_score": candidate.hook_score,
            "hook_reason": candidate.hook_reason,
            "editorial_score": candidate.editorial_score,
            "editorial_reason": candidate.editorial_reason,
            "channel_score": candidate.channel_score,
            "channel_reason": candidate.channel_reason,
            "reason": candidate.reason,
            "frame": str(frame_path) if frame_path.exists() else "",
            "publication": publish_copy,
            "preview": preview_text,
        }
        data["candidates"].append(item)

        lines.extend(
            [
                f"## {rank}. Score {candidate.score}/100 - {score_label(candidate.score)}\n\n",
                f"Decisao: **{candidate_decision(candidate)}**\n\n",
                f"{frame_note}\n\n",
                f"Inicio: `{start}` | Duracao: `{duration}s`\n\n",
                f"Titulo sugerido: **{headline}**\n\n",
                f"Primeira frase: {first_sentence(candidate.text)}\n\n",
                f"Gancho inicial: `{candidate.hook_score}/100` - {candidate.hook_reason}\n\n",
                f"Score editorial: `{candidate.editorial_score}/100` - {candidate.editorial_reason}\n\n",
                f"Score do canal: `{candidate.channel_score:+d}` - {candidate.channel_reason}\n\n",
                f"Motivo do score: {candidate.reason}\n\n",
                "Descricao pronta:\n\n",
                "```text\n",
                publish_copy.strip(),
                "\n```\n\n",
                "Previa da fala:\n\n",
                f"> {preview_text}\n\n",
            ]
        )

    data_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    write_user_text(report_path, "".join(lines))
    return report_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Versao local estilo OpusClip para cortes de TikTok.")
    parser.add_argument("--url", required=True, help="URL do video no YouTube.")
    parser.add_argument("--source", default=None, help="Video local ja baixado. Evita baixar de novo.")
    parser.add_argument("--discard-source", action="store_true", help="Remove o video-fonte baixado ao finalizar. Os cortes finais continuam salvos.")
    parser.add_argument("--count", type=int, default=3, help="Quantidade de cortes.")
    parser.add_argument("--min-duration", type=int, default=60, help="Duracao minima dos cortes.")
    parser.add_argument("--max-duration", type=int, default=90, help="Duracao maxima dos cortes. Padrao mira monetizacao e retencao.")
    parser.add_argument("--editorial-pool", type=int, default=12, help="Quantidade de candidatos avaliados antes de escolher os cortes finais.")
    parser.add_argument("--min-score", type=int, default=70, help="Score minimo.")
    parser.add_argument("--min-source-height", type=int, default=720, help="Altura minima do video-fonte.")
    parser.add_argument("--allow-low-quality", action="store_true", help="Permite fonte abaixo da altura minima.")
    parser.add_argument("--quality", choices=["tiktok", "alta", "4k"], default="alta")
    parser.add_argument("--style", choices=["clean", "hook", "caption-ready"], default="clean")
    parser.add_argument("--burn-subtitles", action="store_true", help="Queima legenda sincronizada no video. Padrao: desligado.")
    parser.add_argument("--animated-subtitles", action="store_true", help="Legendas animadas word-by-word (estilo OpusClip/CapCut) via faster-whisper.")
    parser.add_argument("--regenerate-hook", action="store_true", help="Gera gancho IA (GPT) + narracao Edge-TTS como pre-roll de 3-5s.")
    parser.add_argument("--hook-voice", default="pt-BR-AntonioNeural", help="Voz Edge-TTS para o gancho (pt-BR-AntonioNeural, pt-BR-FranciscaNeural, etc).")
    parser.add_argument("--keep-pauses", action="store_true", help="Mantido por compatibilidade. O padrao ja mantem pausas.")
    parser.add_argument("--cut-pauses", action="store_true", help="Remove pausas/silencios. Use apenas para teste, pois pode afetar sincronia.")
    parser.add_argument("--silence-db", type=int, default=-34, help="Sensibilidade para detectar silencio. Mais alto corta mais.")
    parser.add_argument("--min-silence", type=float, default=0.45, help="Duracao minima de silencio para cortar.")
    parser.add_argument("--focus", choices=["auto", "left", "center", "right"], default="auto")
    parser.add_argument("--min-visual-score", type=int, default=45, help="Score minimo de rosto/enquadramento para renderizar.")
    parser.add_argument("--no-media-score", action="store_true", help="Usa apenas texto/transcricao para ranquear.")
    parser.add_argument("--editorial-ai", choices=["auto", "off", "required"], default="auto", help="auto usa IA se OPENAI_API_KEY existir; off desliga; required exige IA.")
    parser.add_argument("--ai-model", default=None, help="Modelo de IA editorial. Padrao: OPENAI_MODEL ou gpt-4.1-mini.")
    parser.add_argument("--music", default=None)
    parser.add_argument("--music-volume", type=float, default=0.06)
    parser.add_argument("--variants", choices=["single", "ab"], default="single", help="single gera 1 video; ab gera versao limpa e versao zoom.")
    parser.add_argument("--lang", default="pt-orig,pt")
    parser.add_argument("--preview-only", action="store_true", help="Gera relatorio de aprovacao com frames e para antes de renderizar.")
    parser.add_argument("--visual-retries", type=int, default=2, help="Tentativas extras para recentralizar o rosto se o render reprovar.")
    parser.add_argument(
        "--render-decision",
        choices=["APROVAR", "TESTAR", "REJEITAR"],
        default="APROVAR",
        help="Decisao minima para renderizar. Padrao: apenas APROVAR.",
    )
    parser.add_argument(
        "--silent",
        action="store_true",
        help="Mode silencioso: FFmpeg so loga erros (reduz output em 90%%, economiza tokens).",
    )
    args = parser.parse_args()

    print("1/5 Preparando video-fonte...")
    transcript_only_preview = args.preview_only and args.no_media_score and not args.source
    source: Path | None = None
    if transcript_only_preview:
        print("Modo pre-aprovacao rapido: usando apenas transcricao, sem baixar o video-fonte.")
    else:
        source = Path(args.source) if args.source else download_youtube(args.url)
        if args.discard_source and not args.source:
            atexit.register(discard_downloaded_source, source)
        info = probe_video(source)
        print(f"Fonte: {info.width}x{info.height} | audio={'sim' if info.has_audio else 'nao'} | arquivo: {source}")

        if info.height < args.min_source_height and not args.allow_low_quality:
            raise RuntimeError(
                f"Fonte baixa demais: {info.width}x{info.height}. "
                f"Use outro video ou rode com --allow-low-quality se quiser aceitar pixelacao."
            )
        if not info.has_audio:
            raise RuntimeError("O arquivo baixado veio sem audio. Apague esse arquivo em .work\\youtube e rode de novo.")

    print("2/5 Baixando transcricao...")
    subtitles = download_subtitles(args.url, args.lang)
    captions = parse_vtt(subtitles)

    print("3/5 Calculando score dos trechos...")
    signals = None if args.no_media_score or source is None else build_media_signals(source)
    pool_size = max(args.editorial_pool, args.count * 3, args.count)
    candidates = find_candidates(captions, args.min_duration, args.max_duration, pool_size, signals=signals)
    if args.editorial_ai != "off":
        print("3.5/5 Avaliando contexto editorial dos melhores trechos...")
        candidates = judge_candidates(
            candidates,
            enabled=True,
            require_ai=args.editorial_ai == "required",
            model=args.ai_model,
        )
    else:
        for candidate in candidates:
            editorial_score, editorial_reason, title = local_editorial_score(candidate)
            channel_score, channel_reason = learned_score(
                candidate.text,
                " ".join(candidate.text.split()[:38]).lower(),
                max(0.0, candidate.end - candidate.start),
            )
            final_score = round(candidate.score * 0.55 + editorial_score * 0.45)
            candidate.editorial_score = editorial_score
            candidate.editorial_reason = "local: " + editorial_reason
            candidate.channel_score = channel_score
            candidate.channel_reason = channel_reason
            candidate.headline = title
            candidate.reason = f"{candidate.reason}; editorial: {editorial_reason}"
            candidate.score = max(0, min(100, final_score))
        candidates.sort(key=lambda item: item.score, reverse=True)
    candidates = [item for item in candidates if item.score >= args.min_score]
    if not candidates:
        raise RuntimeError("Nenhum corte passou no score minimo.")

    print("3.8/5 Gerando relatorio de aprovacao...")
    preview_report = write_candidate_preview_report(candidates, source, args.url)
    print(f"Relatorio de aprovacao: {preview_report}")
    rejected_report = write_rejected_report(candidates, args.url)
    print(f"Rejeitados: {rejected_report}")
    if args.preview_only:
        print("Previa pronta. Renderizacao pulada por --preview-only.")
        return

    render_candidates = candidates_for_render(candidates, args.render_decision)[: args.count]
    if not render_candidates:
        raise RuntimeError(
            f"Nenhum corte com decisao {args.render_decision} ou melhor. "
            f"Veja o relatorio antes de forcar renderizacao."
        )

    print("4/5 Gerando cortes...")
    created: list[dict] = []
    render_stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for rank, candidate in enumerate(render_candidates, start=1):
        start = seconds_to_timestamp(candidate.start)
        duration = int(candidate.end - candidate.start)
        headline = clean_headline(candidate.headline)
        decision = candidate_decision(candidate)
        focus = args.focus
        focus_timeline = None
        focus_quality = None
        focus_reason = ""
        if focus == "auto":
            focus = detect_face_focus(source, candidate.start, duration)
            focus_analysis = analyze_face_focus(source, candidate.start, duration)
            focus_timeline = [
                (float(segment.start), float(segment.end), float(segment.x), float(segment.y))
                for segment in focus_analysis.segments
            ]
            focus_quality = focus_analysis.quality_score
            focus_reason = focus_analysis.reason
            if focus_quality < args.min_visual_score:
                print(f"  Pulando corte {rank}: qualidade visual {focus_quality}/100 - {focus_reason}")
                continue

        show_hook = args.style in {"hook", "caption-ready"}
        show_headline = False
        hook = hook_from_headline(headline) if show_hook else None

        timeline_note = f" dinamico={len(focus_timeline)} segmentos" if focus_timeline else ""
        quality_note = f" qualidade_visual={focus_quality}/100" if focus_quality is not None else ""
        print(f"Corte {rank}: decisao={decision} score={candidate.score}/100 inicio={start} foco={focus}{timeline_note}{quality_note}")
        render_source = source
        render_start = start
        render_duration = duration
        pause_note = "pausas mantidas para preservar sincronia"
        if args.cut_pauses:
            pause_dir = OUTPUTS / "opus-local" / "sem-pausas" / f"corte-{rank}"
            render_source, render_duration, _ = cut_silences(
                source,
                start,
                duration,
                pause_dir,
                noise_db=args.silence_db,
                min_silence=args.min_silence,
            )
            render_start = "00:00:00" if render_source != source else start
            removed = duration - render_duration
            pause_note = f"pausas removidas: {removed:.1f}s" if removed > 0.5 else "sem pausas relevantes"
            print(f"  {pause_note}")
        subtitle_path = None
        if args.burn_subtitles:
            subtitle_path = write_cut_subtitles(
                captions,
                candidate.start,
                candidate.end,
                OUTPUTS / "opus-local" / "legendas" / f"corte-{rank}",
            )
        variant_specs = [
            {
                "name": "limpa",
                "label": "limpa",
                "motion_style": "standard",
                "music": Path(args.music) if args.music else None,
                "music_volume": args.music_volume,
            }
        ]
        if args.variants == "ab":
            variant_specs.append(
                {
                    "name": "zoom",
                    "label": "zoom-agressivo",
                    "motion_style": "aggressive",
                    "music": Path(args.music) if args.music else None,
                    "music_volume": args.music_volume,
                }
            )

        outputs: list[dict] = []
        for variant in variant_specs:
            print(f"  Renderizando variacao: {variant['label']}")
            attempt_outputs: list[dict] = []
            focus_offset = 0.0
            variant_output = None
            validation = None
            variant_dir = None
            for attempt in range(max(0, args.visual_retries) + 1):
                attempt_name = slugify(str(variant["name"])) if attempt == 0 else f"{slugify(str(variant['name']))}-ajuste-{attempt}"
                variant_dir = (
                    OUTPUTS
                    / "_validacao"
                    / f"{render_stamp}-{rank:02d}-{slugify(headline)}"
                    / attempt_name
                )
                attempt_focus_timeline = shifted_focus_timeline(focus_timeline, focus, render_duration, focus_offset)
                variant_output = create_cut(
                    render_source,
                    render_start,
                    render_duration,
                    headline,
                    show_headline=show_headline,
                    quality=args.quality,
                    hook=hook,
                    show_hook=show_hook,
                    music=variant["music"],
                    music_volume=variant["music_volume"],
                    focus=focus,
                    subtitles=subtitle_path,
                    motion_style=variant["motion_style"],
                    variant_name=str(variant["name"]),
                    focus_timeline=attempt_focus_timeline,
                    output_dir=variant_dir,
                    animated_subtitles=args.animated_subtitles,
                    regenerate_hook=args.regenerate_hook,
                    hook_transcript=candidate.text if args.regenerate_hook else None,
                    hook_voice=args.hook_voice,
                    silent=args.silent,
                )
                validation = validate_rendered_cut(variant_output, render_duration)
                attempt_outputs.append(
                    {
                        "attempt": attempt + 1,
                        "focus_offset": round(focus_offset, 3),
                        "video": str(variant_output),
                        "validation": validation,
                    }
                )
                if validation["ok"]:
                    break
                next_offset = focus_offset_for_attempt(attempt + 1, focus_offset, validation)
                if attempt >= args.visual_retries or next_offset is None or abs(next_offset - focus_offset) < 0.01:
                    break
                print(
                    f"  Ajustando enquadramento: tentativa {attempt + 1} visual={validation['visual']['score']}/100 "
                    f"centro_x={validation['visual'].get('avg_center_x', 0.5)} offset {focus_offset:+.3f}->{next_offset:+.3f}"
                )
                focus_offset = next_offset

            if variant_output is None or validation is None or variant_dir is None:
                continue
            destination_root = OUTPUTS / "aprovados" if validation["ok"] else OUTPUTS / "rejeitados" / "renderizados"
            destination_dir = destination_root / f"{render_stamp}-{rank:02d}-{slugify(headline)}" / slugify(str(variant["name"]))
            if destination_dir.exists():
                shutil.rmtree(destination_dir)
            destination_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(variant_dir), str(destination_dir))
            variant_output = destination_dir / variant_output.name
            quality_result = write_quality_report(variant_output, expected_duration=render_duration, quality=args.quality)
            validation["quality_control"] = quality_result
            if quality_result["status"] == "reprovado":
                validation["ok"] = False
                validation.setdefault("issues", []).append(
                    "controle de qualidade: " + "; ".join(quality_result.get("issues") or ["reprovado"])
                )
            if validation["ok"]:
                print(
                    f"  Validacao OK: {validation['width']}x{validation['height']} "
                    f"{validation['duration']:.1f}s audio={'sim' if validation['has_audio'] else 'nao'} "
                    f"visual={validation['visual']['score']}/100 qualidade={quality_result['score']}/100"
                )
            else:
                print("  [aviso] Validacao encontrou problema: " + "; ".join(validation["issues"]))
            outputs.append(
                {
                    "variant": variant["label"],
                    "video": str(variant_output),
                    "validation": validation,
                    "attempts": attempt_outputs,
                    "focus_offset": round(focus_offset, 3),
                }
            )

        passed_outputs = [variant for variant in outputs if variant.get("validation", {}).get("ok")]
        if not passed_outputs:
            print(f"  Corte {rank} rejeitado na validacao final. Video movido para rejeitados/renderizados.")
            continue
        output = Path(passed_outputs[0]["video"])
        item = {
            "rank": rank,
            "score": candidate.score,
            "classification": score_label(candidate.score),
            "decision": decision,
            "start": start,
            "duration": duration,
            "render_duration": int(render_duration),
            "headline": headline,
            "hook_score": candidate.hook_score,
            "hook_reason": candidate.hook_reason,
            "start_adjustment": candidate.start_adjustment,
            "editorial_score": candidate.editorial_score,
            "editorial_reason": candidate.editorial_reason,
            "channel_score": candidate.channel_score,
            "channel_reason": candidate.channel_reason,
            "publish_time": suggested_publish_time(rank),
            "focus": focus,
            "focus_timeline": focus_timeline or [],
            "focus_quality": focus_quality,
            "focus_reason": focus_reason,
            "reason": candidate.reason,
            "pause_note": pause_note,
            "video": str(output),
            "variants": passed_outputs,
            "rejected_variants": [variant for variant in outputs if not variant.get("validation", {}).get("ok")],
        }
        created.append(item)
        if subtitle_path:
            write_user_text(output.with_name("legendas.srt"), subtitle_path.read_text(encoding="utf-8"))
        metadata_text = (
            "\n".join(
                [
                    f"score={candidate.score}/100",
                    f"classificacao={score_label(candidate.score)}",
                    f"inicio={start}",
                    f"duracao={duration}",
                    f"duracao_render={int(render_duration)}",
                    f"pausas={pause_note}",
                    f"headline={headline}",
                    f"gancho_inicial={candidate.hook_score}/100",
                    f"motivo_gancho={candidate.hook_reason}",
                    f"ajuste_entrada={candidate.start_adjustment:+.1f}s",
                    f"score_editorial={candidate.editorial_score}/100",
                    f"motivo_editorial={candidate.editorial_reason}",
                    f"score_canal={candidate.channel_score:+d}",
                    f"motivo_canal={candidate.channel_reason}",
                    f"foco={focus}",
                    f"foco_dinamico={len(focus_timeline or [])} segmentos",
                    f"qualidade_visual={focus_quality if focus_quality is not None else 'nao analisada'}",
                    f"motivo_visual={focus_reason}",
                    f"motivo={candidate.reason}",
                    f"fonte={args.url}",
                    "variacoes=" + ", ".join(f"{v['variant']} => {v['video']}" for v in outputs),
                ]
            )
            + "\n"
        )
        publication = publication_text(headline, rank, candidate.text, candidate.score)
        for variant in outputs:
            variant_path = Path(variant["video"])
            write_user_text(variant_path.with_name("publicacao.txt"), publication)
            write_user_text(variant_path.with_name("score-viral.txt"), metadata_text)

    if not created:
        raise RuntimeError("Nenhum corte passou na validacao final de audio, formato e rosto centralizado.")

    print("5/5 Salvando indice...")
    index = write_index(created, args.url)
    pack = write_posting_pack(created, args.url)
    print(f"Indice: {index}")
    print(f"Postar agora: {pack}")
    print("Cortes:")
    for item in created:
        print(item["video"])


if __name__ == "__main__":
    main()
