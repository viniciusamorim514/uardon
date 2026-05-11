"""Hardware-accelerated video encoder detection.

Picks the fastest available H.264 encoder at runtime and caches the result.
Order of preference: NVENC > QSV > AMF > libx264 (CPU fallback).

Each encoder returns args equivalent to libx264 quality settings
(CRF 18, veryfast preset, maxrate/bufsize).
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Optional

import imageio_ffmpeg


ROOT = Path(__file__).resolve().parents[1]
CACHE_FILE = ROOT / ".work" / "encoder_cache.json"

DEFAULT_CRF = "18"
DEFAULT_MAXRATE = "35000k"
DEFAULT_BUFSIZE = "70000k"


def _ffmpeg() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def _test_encoder(encoder: str, extra_args: list[str]) -> bool:
    """Try to encode 1 second of test video with the given encoder."""
    try:
        result = subprocess.run(
            [
                _ffmpeg(),
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "testsrc=duration=1:size=320x240:rate=30",
                "-c:v",
                encoder,
                *extra_args,
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            timeout=15,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _detect() -> str:
    """Return name of best available encoder."""
    if os.environ.get("FORCE_CPU_ENCODER"):
        return "libx264"

    candidates = [
        ("h264_nvenc", ["-preset", "p4"]),
        ("h264_qsv", ["-preset", "medium"]),
        ("h264_amf", ["-quality", "balanced"]),
    ]
    for name, args in candidates:
        if _test_encoder(name, args):
            return name
    return "libx264"


def _load_cache() -> Optional[str]:
    if not CACHE_FILE.exists():
        return None
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        return data.get("encoder")
    except (OSError, json.JSONDecodeError):
        return None


def _save_cache(encoder: str) -> None:
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps({"encoder": encoder}), encoding="utf-8")
    except OSError:
        pass


def get_encoder_name() -> str:
    """Return the best H.264 encoder available, caching the result."""
    cached = _load_cache()
    if cached:
        return cached
    encoder = _detect()
    _save_cache(encoder)
    return encoder


def video_encoder_args(
    crf: str = DEFAULT_CRF,
    maxrate: str = DEFAULT_MAXRATE,
    bufsize: str = DEFAULT_BUFSIZE,
    preset: str = "veryfast",
) -> list[str]:
    """Return FFmpeg args for the best available H.264 encoder.

    Quality is mapped across encoders so output looks roughly equivalent.
    """
    encoder = get_encoder_name()
    crf_val = int(crf) if crf.isdigit() else 18

    if encoder == "h264_nvenc":
        # NVENC: -cq is equivalent to CRF (lower = better quality)
        return [
            "-c:v", "h264_nvenc",
            "-preset", "p4",
            "-tune", "hq",
            "-rc", "vbr",
            "-cq", str(crf_val),
            "-b:v", "0",
            "-maxrate", maxrate,
            "-bufsize", bufsize,
        ]

    if encoder == "h264_qsv":
        # QSV: -global_quality is equivalent to CRF
        return [
            "-c:v", "h264_qsv",
            "-preset", "medium",
            "-global_quality", str(crf_val),
            "-look_ahead", "1",
            "-maxrate", maxrate,
            "-bufsize", bufsize,
        ]

    if encoder == "h264_amf":
        return [
            "-c:v", "h264_amf",
            "-quality", "balanced",
            "-rc", "cqp",
            "-qp_i", str(crf_val),
            "-qp_p", str(crf_val),
            "-maxrate", maxrate,
            "-bufsize", bufsize,
        ]

    # CPU fallback
    return [
        "-c:v", "libx264",
        "-preset", preset,
        "-crf", str(crf_val),
        "-maxrate", maxrate,
        "-bufsize", bufsize,
    ]


def reset_cache() -> None:
    """Force re-detection on next call."""
    if CACHE_FILE.exists():
        CACHE_FILE.unlink()


if __name__ == "__main__":
    # CLI: python src/hw_encoder.py [--reset]
    import sys
    if "--reset" in sys.argv:
        reset_cache()
        print("Cache reset.")
    encoder = get_encoder_name()
    print(f"Selected encoder: {encoder}")
    print("FFmpeg args:", " ".join(video_encoder_args()))
