"""Word-by-word animated subtitles (TikTok / OpusClip style).

Uses faster-whisper to get word-level timestamps, then generates an ASS
subtitle file where the *current* word is highlighted while the surrounding
context stays visible — same effect as CapCut / OpusClip viral captions.

CLI:
    python src/animated_subtitles.py --audio clip.mp4 --output clip.ass

Programmatic:
    from animated_subtitles import generate_animated_subtitles
    generate_animated_subtitles(audio_path, ass_path, language="pt")
"""
from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class SubtitleStyle:
    font: str = "Montserrat"
    # Vertical % of video height that the font should occupy. ~6% is the
    # CapCut/TikTok sweet spot — readable on phones without dominating frame.
    font_size_pct: float = 6.0
    primary_color: str = "&H00FFFFFF"   # white (BGR + alpha)
    highlight_color: str = "&H0000ECFF" # yellow #FFEC00 in BGR
    outline_color: str = "&H00000000"   # black outline
    back_color: str = "&H80000000"      # 50% black shadow
    outline: int = 4
    shadow: int = 1
    margin_v_pct: float = 18.0           # % of height from bottom (TikTok safe area)
    words_per_group: int = 3             # words shown together per frame
    max_chars_per_group: int = 22        # break early on long words


def _format_time(seconds: float) -> str:
    """ASS time format: H:MM:SS.cs"""
    if seconds < 0:
        seconds = 0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def _transcribe_faster_whisper(audio_path: Path, language: str, model_size: str) -> list[Word]:
    """Transcribe using faster-whisper (preferred — 4x faster)."""
    from faster_whisper import WhisperModel
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(
        str(audio_path),
        language=language,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 300},
    )
    words: list[Word] = []
    for segment in segments:
        for w in (segment.words or []):
            text = (w.word or "").strip()
            if not text:
                continue
            words.append(Word(text=text, start=float(w.start), end=float(w.end)))
    return words


def _transcribe_openai_whisper(audio_path: Path, language: str, model_size: str) -> list[Word]:
    """Fallback: openai-whisper with word-level timestamps."""
    import whisper
    model = whisper.load_model(model_size)
    result = model.transcribe(
        str(audio_path),
        language=language,
        word_timestamps=True,
        verbose=False,
    )
    words: list[Word] = []
    for seg in result.get("segments", []):
        for w in seg.get("words", []):
            text = (w.get("word") or "").strip()
            if not text:
                continue
            words.append(Word(text=text, start=float(w["start"]), end=float(w["end"])))
    return words


def words_from_vtt(vtt_path: Path, clip_start_s: float, clip_duration_s: float) -> list[Word]:
    """Parse a YouTube VTT file and distribute word timings proportionally.

    This is the zero-dependency fallback: no ML model needed.  Each VTT cue
    gives start/end for a phrase; we spread that range evenly across words.
    """
    import re as _re

    text = vtt_path.read_text(encoding="utf-8", errors="ignore")
    clip_end_s = clip_start_s + clip_duration_s

    # Match timestamp lines: 00:01:23.456 --> 00:01:25.789
    cue_pattern = _re.compile(
        r"(\d+:\d{2}:\d{2}\.\d+|\d{2}:\d{2}\.\d+)\s*-->\s*(\d+:\d{2}:\d{2}\.\d+|\d{2}:\d{2}\.\d+)"
    )

    def to_s(t: str) -> float:
        parts = t.strip().split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        return int(parts[0]) * 60 + float(parts[1])

    lines = text.splitlines()
    words: list[Word] = []
    i = 0
    while i < len(lines):
        m = cue_pattern.match(lines[i])
        if m:
            cue_start = to_s(m.group(1))
            cue_end = to_s(m.group(2))
            # Skip cues outside clip range (with small tolerance)
            if cue_end < clip_start_s - 1 or cue_start > clip_end_s + 1:
                i += 1
                continue
            # Collect cue text (lines after timestamp until blank or next cue)
            i += 1
            phrase_lines = []
            while i < len(lines) and lines[i].strip() and not cue_pattern.match(lines[i]):
                # Strip VTT tags like <c>, </c>, <00:00:00.000>
                clean = _re.sub(r"<[^>]+>", "", lines[i]).strip()
                if clean:
                    phrase_lines.append(clean)
                i += 1
            phrase = " ".join(phrase_lines)
            phrase = _re.sub(r"\s+", " ", phrase).strip()
            if not phrase:
                continue
            phrase_words = phrase.split()
            if not phrase_words:
                continue
            # Adjust times relative to clip start
            rel_start = max(0.0, cue_start - clip_start_s)
            rel_end = min(clip_duration_s, cue_end - clip_start_s)
            if rel_end <= rel_start:
                rel_end = rel_start + 0.5 * len(phrase_words)
            duration_per_word = (rel_end - rel_start) / len(phrase_words)
            for j, w in enumerate(phrase_words):
                ws = rel_start + j * duration_per_word
                we = rel_start + (j + 1) * duration_per_word
                words.append(Word(text=w, start=round(ws, 3), end=round(we, 3)))
        else:
            i += 1

    # Deduplicate: VTT often repeats lines with slightly different timestamps
    seen: set[tuple] = set()
    unique: list[Word] = []
    for w in words:
        key = (w.text.lower(), round(w.start, 1))
        if key not in seen:
            seen.add(key)
            unique.append(w)
    return unique


def transcribe_words(
    audio_path: Path,
    language: str = "pt",
    model_size: str = "small",
    vtt_path: Path | None = None,
    clip_start_s: float = 0.0,
    clip_duration_s: float = 0.0,
) -> list[Word]:
    """Transcribe audio returning word-level timestamps.

    Priority:
    1. faster-whisper (fastest, local)
    2. openai-whisper (fallback for Python 3.14 where ctranslate2 crashes)
    3. YouTube VTT proportional estimation (zero-dependency fallback)
    """
    try:
        return _transcribe_faster_whisper(audio_path, language, model_size)
    except Exception as exc:
        print(f"[animated-subtitles] faster-whisper falhou ({type(exc).__name__}); tentando openai-whisper...", flush=True)

    try:
        return _transcribe_openai_whisper(audio_path, language, model_size)
    except Exception as exc:
        print(f"[animated-subtitles] openai-whisper falhou ({type(exc).__name__}); usando VTT do YouTube...", flush=True)

    if vtt_path and vtt_path.exists():
        words = words_from_vtt(vtt_path, clip_start_s, clip_duration_s)
        if words:
            print(f"[animated-subtitles] VTT OK — {len(words)} palavras extraidas.", flush=True)
            return words

    raise RuntimeError(
        "Nenhum backend disponivel para legendas animadas. "
        "Verifique faster-whisper, openai-whisper, ou forneça --vtt-path."
    )


def group_words(
    words: list[Word],
    style: SubtitleStyle,
) -> list[list[Word]]:
    """Group words into small chunks (3 words per frame by default).

    Caps groups by character count to avoid awkward layouts on long words.
    """
    groups: list[list[Word]] = []
    current: list[Word] = []
    current_chars = 0

    for w in words:
        word_len = len(w.text) + 1  # space
        would_overflow = (
            len(current) >= style.words_per_group
            or current_chars + word_len > style.max_chars_per_group
        )
        if current and would_overflow:
            groups.append(current)
            current = []
            current_chars = 0
        current.append(w)
        current_chars += word_len

    if current:
        groups.append(current)
    return groups


def _ass_header(style: SubtitleStyle, video_width: int = 1080, video_height: int = 1920) -> str:
    """ASS file header with styling."""
    fontsize = max(20, int(video_height * style.font_size_pct / 100))
    margin_v = max(40, int(video_height * style.margin_v_pct / 100))
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {video_width}
PlayResY: {video_height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style.font},{fontsize},{style.primary_color},{style.highlight_color},{style.outline_color},{style.back_color},1,0,0,0,100,100,0,0,1,{style.outline},{style.shadow},2,40,40,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _build_event_text(group: list[Word], current_idx: int, style: SubtitleStyle) -> str:
    """Build the {tag}word{tag}word... line, highlighting current word."""
    parts: list[str] = []
    for i, w in enumerate(group):
        text = w.text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
        if i == current_idx:
            # Current word: highlight color + slight scale-up bounce
            parts.append(
                f"{{\\c{style.highlight_color}\\fscx110\\fscy110}}{text}{{\\r}}"
            )
        else:
            parts.append(text)
    return " ".join(parts)


def words_to_ass(words: list[Word], style: SubtitleStyle, video_width: int = 1080, video_height: int = 1920) -> str:
    """Convert word list to a complete ASS subtitle document with karaoke highlight."""
    out = [_ass_header(style, video_width, video_height)]
    groups = group_words(words, style)

    for group in groups:
        for idx, w in enumerate(group):
            start = _format_time(w.start)
            end = _format_time(w.end)
            text = _build_event_text(group, idx, style)
            out.append(
                f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}"
            )

    return "\n".join(out) + "\n"


def generate_animated_subtitles(
    audio_path: Path,
    output_path: Path,
    language: str = "pt",
    model_size: str = "small",
    style: Optional[SubtitleStyle] = None,
    video_width: int = 1080,
    video_height: int = 1920,
    vtt_path: Optional[Path] = None,
    clip_start_s: float = 0.0,
    clip_duration_s: float = 0.0,
) -> Path:
    """Full pipeline: audio file → animated .ass subtitle file."""
    style = style or SubtitleStyle()
    words = transcribe_words(
        audio_path,
        language=language,
        model_size=model_size,
        vtt_path=vtt_path,
        clip_start_s=clip_start_s,
        clip_duration_s=clip_duration_s,
    )
    if not words:
        raise RuntimeError("No words transcribed — audio may be silent or unsupported.")
    ass_content = words_to_ass(words, style, video_width, video_height)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(ass_content, encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate word-by-word animated subtitles.")
    parser.add_argument("--audio", required=True, help="Path to audio/video file.")
    parser.add_argument("--output", required=True, help="Output .ass path.")
    parser.add_argument("--language", default="pt", help="Language code (default: pt).")
    parser.add_argument("--model", default="small", help="Whisper model size (tiny/base/small/medium).")
    parser.add_argument("--width", type=int, default=1080)
    parser.add_argument("--height", type=int, default=1920)
    args = parser.parse_args()

    out = generate_animated_subtitles(
        Path(args.audio),
        Path(args.output),
        language=args.language,
        model_size=args.model,
        video_width=args.width,
        video_height=args.height,
    )
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
