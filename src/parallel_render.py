"""Parallel segment rendering for faster video output.

Split a video into segments, render each in parallel,
then concatenate. Can provide 3-4x speedup on multi-core systems.

Key: All segments use identical filter chains (zoompan, subtitles, etc.)
so they can be safely concatenated with FFmpeg concat demuxer.

Usage:
    result = parallel_render_cut(
        source=Path("source.mp4"),
        start="0:00:10",
        duration=60.0,
        headline="Meu Titulo",
        quality="alta",
        segment_duration=10.0,  # render 10s chunks in parallel
        max_workers=4,
    )
"""
from __future__ import annotations

import concurrent.futures
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import imageio_ffmpeg

from create_cut_from_source import (
    create_cut,
    slugify,
    render_size,
    build_filter,
    OUTPUTS,
)


@dataclass
class SegmentRenderResult:
    """Result from parallel segment rendering."""
    success: bool
    output: Optional[str] = None
    duration_s: float = 0.0
    segments_rendered: int = 0
    total_segments: int = 0
    error: Optional[str] = None
    speedup_factor: float = 1.0


def ffmpeg_path() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def _estimate_segment_count(total_duration: float, segment_duration: float) -> int:
    """Estimate number of segments needed."""
    return max(1, int(total_duration / segment_duration) + (1 if total_duration % segment_duration > 0.5 else 0))


def _time_to_seconds(time_str: str) -> float:
    """Convert HH:MM:SS or MM:SS to seconds."""
    parts = time_str.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(time_str)


def _seconds_to_time(seconds: float) -> str:
    """Convert seconds to HH:MM:SS format."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def render_segment(
    source: Path,
    segment_idx: int,
    segment_start_s: float,
    segment_duration_s: float,
    total_duration_s: float,
    headline: str,
    show_headline: bool,
    quality: str,
    hook: Optional[str],
    show_hook: bool,
    focus: str,
    subtitles: Optional[Path],
    motion_style: str,
    music: Optional[Path],
    music_volume: float,
    remove_source_text: bool,
    work_dir: Path,
    silent: bool = False,
) -> tuple[int, Optional[Path], str]:
    """Render a single segment. Returns (segment_idx, output_path, error_msg)."""
    try:
        start_time = _seconds_to_time(segment_start_s)
        segment_dir = work_dir / f"segment-{segment_idx:03d}"
        segment_dir.mkdir(parents=True, exist_ok=True)

        # For each segment, use create_cut with the segment's start time and duration
        output = create_cut(
            source,
            start_time,
            min(segment_duration_s, total_duration_s - segment_start_s),  # Don't exceed total
            f"{headline} [seg {segment_idx}]",
            show_headline=show_headline,
            quality=quality,
            hook=hook if segment_idx == 0 else None,  # Only show hook on first segment
            show_hook=show_hook and segment_idx == 0,
            music=music,
            music_volume=music_volume,
            focus=focus,
            subtitles=subtitles,
            motion_style=motion_style,
            variant_name=f"segment-{segment_idx}",
            remove_source_text=remove_source_text,
            output_dir=segment_dir,
            silent=silent,
        )

        return segment_idx, output, ""

    except Exception as e:
        return segment_idx, None, f"Segment {segment_idx}: {type(e).__name__}: {e}"


def concatenate_segments(
    segments: list[Path],
    output_path: Path,
    silent: bool = False,
) -> bool:
    """Concatenate segment MP4s using FFmpeg concat demuxer.

    Returns True if successful.
    """
    try:
        # Create concat demuxer file list
        concat_file = output_path.parent / "concat_list.txt"
        with open(concat_file, "w") as f:
            for seg in segments:
                # FFmpeg concat protocol: file 'path'
                f.write(f"file '{seg.resolve()}'\n")

        cmd = [
            ffmpeg_path(),
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
            "-c", "copy",  # No re-encoding, just mux
            "-movflags", "+faststart",
            str(output_path),
        ]

        if silent:
            cmd.extend(["-loglevel", "error", "-hide_banner"])

        subprocess.run(cmd, check=True, capture_output=True, text=True)
        concat_file.unlink()
        return True

    except Exception as e:
        print(f"[concat] Error: {e}", flush=True)
        return False


def parallel_render_cut(
    source: Path,
    start: str,
    duration: float,
    headline: str,
    show_headline: bool = True,
    quality: str = "alta",
    hook: str | None = None,
    show_hook: bool = True,
    music: Path | None = None,
    music_volume: float = 0.07,
    focus: str = "center",
    subtitles: Path | None = None,
    motion_style: str = "standard",
    remove_source_text: bool = True,
    output_dir: Path | None = None,
    segment_duration: float = 10.0,
    max_workers: int = 4,
    silent: bool = False,
) -> SegmentRenderResult:
    """Render a cut using parallel segment processing.

    Splits timeline into segments, renders each in parallel,
    then concatenates for final output.

    Args:
        segment_duration: Size of each segment in seconds (default 10s)
        max_workers: Max parallel processes (default 4, adapt to CPU count)
        (other args same as create_cut)

    Returns:
        SegmentRenderResult with success status and speedup factor estimate.
    """
    if not source.exists():
        return SegmentRenderResult(
            success=False,
            error=f"Source not found: {source}",
        )

    # Estimate segments
    segment_count = _estimate_segment_count(duration, segment_duration)

    # If only 1 segment, fall back to single render (faster path)
    if segment_count == 1:
        try:
            output = create_cut(
                source, start, duration, headline,
                show_headline=show_headline, quality=quality, hook=hook, show_hook=show_hook,
                music=music, music_volume=music_volume, focus=focus, subtitles=subtitles,
                motion_style=motion_style, remove_source_text=remove_source_text,
                output_dir=output_dir, silent=silent,
            )
            return SegmentRenderResult(
                success=True,
                output=str(output),
                duration_s=duration,
                segments_rendered=1,
                total_segments=1,
                speedup_factor=1.0,
            )
        except Exception as e:
            return SegmentRenderResult(
                success=False,
                error=str(e),
                segments_rendered=0,
                total_segments=1,
            )

    # Multi-segment parallel rendering
    work_dir = Path(tempfile.mkdtemp(prefix="parallel-render-"))
    segment_start_s = 0.0
    start_seconds = _time_to_seconds(start)

    try:
        # Submit segment render jobs
        futures = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            for seg_idx in range(segment_count):
                seg_start = start_seconds + segment_start_s
                future = executor.submit(
                    render_segment,
                    source, seg_idx, segment_start_s, segment_duration,
                    duration, headline, show_headline, quality, hook, show_hook,
                    focus, subtitles, motion_style, music, music_volume,
                    remove_source_text, work_dir, silent,
                )
                futures[future] = seg_idx
                segment_start_s += segment_duration

            # Collect results
            segments: dict[int, Path] = {}
            errors = []
            for future in concurrent.futures.as_completed(futures):
                seg_idx, output_path, error = future.result()
                if error:
                    errors.append(error)
                else:
                    segments[seg_idx] = output_path

        # Check for errors
        if errors:
            return SegmentRenderResult(
                success=False,
                segments_rendered=len(segments),
                total_segments=segment_count,
                error=" | ".join(errors),
            )

        # Sort segments by index and concatenate
        segment_paths = [segments[i] for i in sorted(segments.keys())]
        if len(segment_paths) != segment_count:
            return SegmentRenderResult(
                success=False,
                segments_rendered=len(segment_paths),
                total_segments=segment_count,
                error=f"Missing segments: got {len(segment_paths)}, expected {segment_count}",
            )

        # Concatenate
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_dir = output_dir or OUTPUTS / f"{stamp}-parallel-{slugify(headline)}"
        out_dir.mkdir(parents=True, exist_ok=True)
        output_name = {
            "4k": "corte-vertical-4k.mp4",
            "alta": "corte-vertical-alta.mp4",
            "tiktok": "corte-vertical-tiktok.mp4",
        }[quality]
        final_output = out_dir / output_name

        if not concatenate_segments(segment_paths, final_output, silent=silent):
            return SegmentRenderResult(
                success=False,
                segments_rendered=segment_count,
                total_segments=segment_count,
                error="Concatenation failed",
            )

        # Estimate speedup (very rough: segments rendered in parallel, so time ≈ longest segment)
        # vs sequential which would be segment_count * segment_time
        speedup = min(max_workers, segment_count)

        return SegmentRenderResult(
            success=True,
            output=str(final_output),
            duration_s=duration,
            segments_rendered=segment_count,
            total_segments=segment_count,
            speedup_factor=speedup,
        )

    except Exception as e:
        return SegmentRenderResult(
            success=False,
            error=str(e),
        )

    finally:
        # Cleanup temp directory
        try:
            shutil.rmtree(work_dir, ignore_errors=True)
        except:
            pass


if __name__ == "__main__":
    from datetime import datetime
    print("Parallel render module. Import and call parallel_render_cut()")
