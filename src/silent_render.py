"""Silent rendering wrapper for create_cut_from_source.

Runs create_cut() with FFmpeg in silent mode (only errors logged).
Provides a structured result dict instead of stdout parsing.

Usage:
    from silent_render import create_cut_silent
    result = create_cut_silent(source, "0:00:10", 60.0, "Meu Titulo", quality="alta")
    if result['success']:
        print(f"Output: {result['output']}")
    else:
        print(f"Error: {result['error']}")
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from create_cut_from_source import create_cut


@dataclass
class RenderResult:
    """Result from a silent render operation."""
    success: bool
    output: Optional[str] = None
    duration_s: float = 0.0
    filesize_kb: float = 0.0
    error: Optional[str] = None


def create_cut_silent(
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
    variant_name: str | None = None,
    focus_timeline: list[tuple[float, float, float]] | None = None,
    remove_source_text: bool = True,
    output_dir: Path | None = None,
    animated_subtitles: bool = False,
    regenerate_hook: bool = False,
    hook_transcript: str | None = None,
    hook_voice: str = "pt-BR-AntonioNeural",
) -> RenderResult:
    """Create a cut with silent FFmpeg rendering.

    Returns structured result without stdout/stderr noise.

    Args:
        (all same as create_cut)

    Returns:
        RenderResult with success status, output path, filesize, or error message.
    """
    try:
        output_path = create_cut(
            source,
            start,
            duration,
            headline,
            show_headline=show_headline,
            quality=quality,
            hook=hook,
            show_hook=show_hook,
            music=music,
            music_volume=music_volume,
            focus=focus,
            subtitles=subtitles,
            motion_style=motion_style,
            variant_name=variant_name,
            focus_timeline=focus_timeline,
            remove_source_text=remove_source_text,
            output_dir=output_dir,
            animated_subtitles=animated_subtitles,
            regenerate_hook=regenerate_hook,
            hook_transcript=hook_transcript,
            hook_voice=hook_voice,
            silent=True,  # KEY: Silent mode enabled
        )

        if output_path.exists():
            filesize = output_path.stat().st_size
            return RenderResult(
                success=True,
                output=str(output_path),
                duration_s=duration,
                filesize_kb=filesize / 1024.0,
                error=None,
            )
        else:
            return RenderResult(
                success=False,
                output=None,
                duration_s=duration,
                filesize_kb=0.0,
                error=f"Output file not created: {output_path}",
            )

    except Exception as exc:
        return RenderResult(
            success=False,
            output=None,
            duration_s=duration,
            filesize_kb=0.0,
            error=f"{type(exc).__name__}: {exc}",
        )
