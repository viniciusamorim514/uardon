from __future__ import annotations

import re
import subprocess
from pathlib import Path

import imageio_ffmpeg

from hw_encoder import video_encoder_args


def ffmpeg_path() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def run_capture(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=False, capture_output=True, text=True, encoding="utf-8", errors="ignore")


def run(args: list[str]) -> None:
    subprocess.run(args, check=True)


def detect_silences(source: Path, start: str, duration: float, noise_db: int = -34, min_silence: float = 0.45) -> list[tuple[float, float]]:
    result = run_capture(
        [
            ffmpeg_path(),
            "-hide_banner",
            "-ss",
            start,
            "-t",
            f"{duration:.3f}",
            "-i",
            str(source),
            "-af",
            f"silencedetect=noise={noise_db}dB:d={min_silence:.2f}",
            "-f",
            "null",
            "-",
        ]
    )
    text = (result.stderr or "") + "\n" + (result.stdout or "")
    starts = [float(value) for value in re.findall(r"silence_start:\s*([0-9.]+)", text)]
    ends = [float(value) for value in re.findall(r"silence_end:\s*([0-9.]+)", text)]
    silences: list[tuple[float, float]] = []
    for index, silence_start in enumerate(starts):
        silence_end = ends[index] if index < len(ends) else duration
        silence_start = max(0.0, min(duration, silence_start))
        silence_end = max(silence_start, min(duration, silence_end))
        if silence_end - silence_start >= min_silence:
            silences.append((silence_start, silence_end))
    return silences


def speech_segments(
    duration: float,
    silences: list[tuple[float, float]],
    keep_silence: float = 0.16,
    min_segment: float = 1.2,
) -> list[tuple[float, float]]:
    segments: list[tuple[float, float]] = []
    cursor = 0.0
    for silence_start, silence_end in silences:
        end = min(duration, silence_start + keep_silence)
        if end - cursor >= min_segment:
            segments.append((cursor, end))
        cursor = max(cursor, silence_end - keep_silence)
    if duration - cursor >= min_segment:
        segments.append((cursor, duration))
    if not segments:
        return [(0.0, duration)]
    return segments


def concat_segments(source: Path, start: str, segments: list[tuple[float, float]], output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    list_file = output.parent / "partes.txt"

    for index, (relative_start, relative_end) in enumerate(segments, start=1):
        part = output.parent / f"parte-{index:03d}.mp4"
        parts.append(part)
        run(
            [
                ffmpeg_path(),
                "-y",
                "-ss",
                start,
                "-ss",
                f"{relative_start:.3f}",
                "-t",
                f"{relative_end - relative_start:.3f}",
                "-i",
                str(source),
                *video_encoder_args(crf="18", preset="ultrafast"),
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                str(part),
            ]
        )

    list_file.write_text(
        "".join(f"file '{part.resolve().as_posix()}'\n" for part in parts),
        encoding="utf-8",
    )
    run(
        [
            ffmpeg_path(),
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            str(output),
        ]
    )
    return output


def cut_silences(
    source: Path,
    start: str,
    duration: float,
    work_dir: Path,
    noise_db: int = -34,
    min_silence: float = 0.45,
    keep_silence: float = 0.16,
) -> tuple[Path, float, list[tuple[float, float]]]:
    silences = detect_silences(source, start, duration, noise_db=noise_db, min_silence=min_silence)
    segments = speech_segments(duration, silences, keep_silence=keep_silence)
    new_duration = sum(end - begin for begin, end in segments)
    if len(segments) <= 1 or new_duration >= duration * 0.96:
        return source, duration, [(0.0, duration)]
    output = work_dir / "fonte-sem-pausas.mp4"
    concat_segments(source, start, segments, output)
    return output, new_duration, [(0.0, new_duration)]
