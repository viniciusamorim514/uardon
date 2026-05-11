from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import imageio_ffmpeg


@dataclass
class VideoInfo:
    width: int
    height: int
    duration: float
    bitrate: int
    has_audio: bool


def probe_video(path: Path) -> VideoInfo:
    result = subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-hide_banner",
            "-i",
            str(path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    text = result.stderr + "\n" + result.stdout
    video_line = next((line for line in text.splitlines() if " Video: " in line), "")
    audio_line = next((line for line in text.splitlines() if " Audio: " in line), "")
    duration_line = next((line for line in text.splitlines() if "Duration:" in line), "")
    size_match = re.search(r"(\d{2,5})x(\d{2,5})", video_line)
    duration_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", duration_line)
    bitrate_match = re.search(r"bitrate:\s*(\d+)\s*kb/s", duration_line)
    width = int(size_match.group(1)) if size_match else 0
    height = int(size_match.group(2)) if size_match else 0
    duration = 0.0
    if duration_match:
        duration = (
            int(duration_match.group(1)) * 3600
            + int(duration_match.group(2)) * 60
            + float(duration_match.group(3))
        )
    return VideoInfo(
        width=width,
        height=height,
        duration=duration,
        bitrate=(int(bitrate_match.group(1)) * 1000 if bitrate_match else 0),
        has_audio=bool(audio_line),
    )
