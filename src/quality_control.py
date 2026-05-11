from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import imageio_ffmpeg

from video_probe import probe_video


def run_decode_check(video_path: Path) -> tuple[bool, list[str]]:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    checks = [
        ["-t", "14"],
        ["-sseof", "-8", "-t", "8"],
    ]
    all_lines: list[str] = []
    ok = True
    for extra in checks:
        result = subprocess.run(
            [
                ffmpeg,
                "-v",
                "error",
                *extra,
                "-i",
                str(video_path),
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        lines = [line.strip() for line in (result.stderr or "").splitlines() if line.strip()]
        all_lines.extend(lines)
        ok = ok and result.returncode == 0 and not lines
    return ok, all_lines[:8]


def sample_visual_metrics(video_path: Path, samples: int = 6) -> dict[str, float]:
    try:
        import cv2
    except Exception:
        return {
            "sharpness": 0.0,
            "border_black_ratio": 0.0,
            "samples": 0.0,
            "face_quality": 0.0,
            "face_coverage": 0.0,
            "face_reason": "OpenCV indisponivel",
        }

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return {
            "sharpness": 0.0,
            "border_black_ratio": 0.0,
            "samples": 0.0,
            "face_quality": 0.0,
            "face_coverage": 0.0,
            "face_reason": "nao abriu video",
        }

    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if frame_count <= 0:
        cap.release()
        return {
            "sharpness": 0.0,
            "border_black_ratio": 0.0,
            "samples": 0.0,
            "face_quality": 0.0,
            "face_coverage": 0.0,
            "face_reason": "sem frames",
        }

    sharpness_values: list[float] = []
    border_values: list[float] = []
    face_centers: list[tuple[float, float]] = []
    face_areas: list[float] = []
    detector = cv2.CascadeClassifier(str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"))
    for index in range(samples):
        frame_index = int(frame_count * (index + 0.5) / samples)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = cap.read()
        if not ok:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        sharpness_values.append(float(cv2.Laplacian(gray, cv2.CV_64F).var()))

        height, width = gray.shape[:2]
        band_h = max(1, int(height * 0.045))
        band_w = max(1, int(width * 0.045))
        bands = [
            gray[:band_h, :],
            gray[-band_h:, :],
            gray[:, :band_w],
            gray[:, -band_w:],
        ]
        black_pixels = sum(int((band < 14).sum()) for band in bands)
        total_pixels = sum(int(band.size) for band in bands)
        border_values.append(black_pixels / max(total_pixels, 1))

        if not detector.empty():
            scale = min(1.0, 420 / max(width, height))
            small = cv2.resize(gray, (max(1, int(width * scale)), max(1, int(height * scale))))
            faces = detector.detectMultiScale(small, scaleFactor=1.08, minNeighbors=4, minSize=(28, 28))
            if len(faces):
                x, y, w, h = max(faces, key=lambda item: item[2] * item[3])
                small_h, small_w = small.shape[:2]
                face_centers.append(((x + w / 2) / max(small_w, 1), (y + h / 2) / max(small_h, 1)))
                face_areas.append((w * h) / max(small_w * small_h, 1))

    cap.release()
    face_coverage = len(face_centers) / max(len(sharpness_values), 1)
    avg_area = sum(face_areas) / max(len(face_areas), 1)
    avg_x_error = sum(abs(x - 0.5) for x, _ in face_centers) / max(len(face_centers), 1)
    avg_y_error = sum(abs(y - 0.45) for _, y in face_centers) / max(len(face_centers), 1)
    face_quality = 100
    face_reasons: list[str] = []
    if face_coverage < 0.35:
        face_quality -= 45
        face_reasons.append("rosto aparece pouco")
    elif face_coverage < 0.6:
        face_quality -= 22
        face_reasons.append("rosto intermitente")
    else:
        face_reasons.append("rosto detectado")
    if avg_area < 0.01:
        face_quality -= 25
        face_reasons.append("rosto pequeno")
    if avg_x_error > 0.18:
        face_quality -= 24
        face_reasons.append("rosto fora do centro")
    elif avg_x_error > 0.10:
        face_quality -= 10
        face_reasons.append("centro do rosto aceitavel")
    else:
        face_reasons.append("rosto centralizado")
    if avg_y_error > 0.22:
        face_quality -= 12
        face_reasons.append("altura do rosto irregular")
    return {
        "sharpness": round(sum(sharpness_values) / max(len(sharpness_values), 1), 2),
        "border_black_ratio": round(sum(border_values) / max(len(border_values), 1), 4),
        "samples": float(len(sharpness_values)),
        "face_quality": float(max(0, min(100, round(face_quality)))),
        "face_coverage": round(face_coverage, 3),
        "face_reason": ", ".join(face_reasons) or "sem rosto detectado",
    }


def expected_dimensions(quality: str) -> tuple[int, int]:
    if quality == "4k":
        return 2160, 3840
    if quality == "alta":
        return 1440, 2560
    return 1080, 1920


def analyze_quality(video_path: Path, expected_duration: float | None = None, quality: str = "alta") -> dict:
    info = probe_video(video_path)
    expected_width, expected_height = expected_dimensions(quality)
    decode_ok, decode_errors = run_decode_check(video_path)
    visual = sample_visual_metrics(video_path)
    short_mode = bool(expected_duration and expected_duration <= 30)

    score = 100
    issues: list[str] = []
    warnings: list[str] = []
    critical = False

    if not decode_ok:
        score -= 35
        critical = True
        issues.append("erro de decodificacao no arquivo final")

    if not info.has_audio:
        score -= 35
        critical = True
        issues.append("video sem audio")

    aspect = info.width / max(info.height, 1)
    if not 0.54 <= aspect <= 0.58:
        score -= 25
        critical = True
        issues.append("formato nao esta em 9:16")

    if info.width < 1080 or info.height < 1920:
        score -= 25
        critical = True
        issues.append("resolucao abaixo do minimo TikTok")
    elif info.width < expected_width or info.height < expected_height:
        score -= 8
        warnings.append("resolucao abaixo do modo selecionado")

    if expected_duration and info.duration < expected_duration * (0.65 if short_mode else 0.75):
        score -= 18
        critical = True
        issues.append("duracao final muito menor que o trecho escolhido")
    elif expected_duration and short_mode and info.duration < expected_duration * 0.80:
        score -= 6
        warnings.append("short ficou um pouco menor que o planejado")
    elif expected_duration and abs(info.duration - expected_duration) > 6:
        score -= 6
        warnings.append("duracao final diferente do planejado")

    if info.bitrate and info.bitrate < 3_500_000:
        score -= 10
        warnings.append("bitrate baixo para corte premium")

    if visual["samples"] > 0:
        if visual["sharpness"] < 1.2:
            score -= 16
            critical = True
            issues.append("imagem muito borrada")
        elif visual["sharpness"] < 2.5:
            score -= 8
            warnings.append("nitidez baixa; revisar visualmente")
        elif visual["sharpness"] < 3.2:
            score -= 4
            warnings.append("nitidez moderada")
        if visual["border_black_ratio"] > 0.55:
            score -= 14
            warnings.append("possiveis bordas pretas ou area inutil no enquadramento")

    face_quality = float(visual.get("face_quality", 0.0))
    if face_quality < 45:
        score -= 18
        warnings.append("foco no rosto precisa revisao")
    elif face_quality < 70:
        score -= 8
        warnings.append("foco no rosto aceitavel, mas nao perfeito")

    final_score = max(0, min(100, round(score)))
    if critical or final_score < 60:
        status = "reprovado"
    elif final_score < 80 or warnings:
        status = "revisar"
    else:
        status = "aprovado"

    return {
        "status": status,
        "score": final_score,
        "video": str(video_path),
        "width": info.width,
        "height": info.height,
        "duration": round(info.duration, 2),
        "bitrate": info.bitrate,
        "has_audio": info.has_audio,
        "decode_ok": decode_ok,
        "decode_errors": decode_errors,
        "sharpness": visual["sharpness"],
        "border_black_ratio": visual["border_black_ratio"],
        "face_quality": int(face_quality),
        "face_coverage": visual["face_coverage"],
        "face_reason": visual["face_reason"],
        "short_mode": short_mode,
        "issues": issues,
        "warnings": warnings,
    }


def write_quality_report(video_path: Path, expected_duration: float | None = None, quality: str = "alta") -> dict:
    result = analyze_quality(video_path, expected_duration=expected_duration, quality=quality)
    out_dir = video_path.parent
    (out_dir / "qualidade.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"status={result['status']}",
        f"score={result['score']}/100",
        f"resolucao={result['width']}x{result['height']}",
        f"duracao={result['duration']}s",
        f"bitrate={result['bitrate']}",
        f"audio={'sim' if result['has_audio'] else 'nao'}",
        f"decode_ok={'sim' if result['decode_ok'] else 'nao'}",
        f"nitidez={result['sharpness']}",
        f"bordas_pretas={result['border_black_ratio']}",
        f"foco_rosto={result['face_quality']}/100",
        f"cobertura_rosto={result['face_coverage']}",
        f"motivo_foco={result['face_reason']}",
        f"modo_curto={'sim' if result.get('short_mode') else 'nao'}",
    ]
    if result["issues"]:
        lines.append("problemas=" + "; ".join(result["issues"]))
    if result["warnings"]:
        lines.append("avisos=" + "; ".join(result["warnings"]))
    (out_dir / "qualidade.txt").write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Valida qualidade tecnica de um corte final.")
    parser.add_argument("video")
    parser.add_argument("--expected-duration", type=float, default=None)
    parser.add_argument("--quality", choices=["tiktok", "alta", "4k"], default="alta")
    args = parser.parse_args()
    result = write_quality_report(Path(args.video), expected_duration=args.expected_duration, quality=args.quality)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
