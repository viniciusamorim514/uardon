from __future__ import annotations

import argparse
import re
import subprocess
from datetime import datetime
from pathlib import Path

import imageio_ffmpeg

from hw_encoder import video_encoder_args


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
VIDEO_CRF = "18"
VIDEO_MAXRATE = "35000k"
VIDEO_BUFSIZE = "70000k"


def ffmpeg_path() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def run_ffmpeg(args: list[str], silent: bool = False) -> None:
    ffmpeg_args = [ffmpeg_path(), "-y"]
    if silent:
        ffmpeg_args.extend(["-loglevel", "error", "-hide_banner"])
    ffmpeg_args.extend(args)
    subprocess.run(ffmpeg_args, check=True)


def run_capture(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=False, capture_output=True, text=True, encoding="utf-8", errors="ignore")


def probe_stream_duration(path: Path, selector: str) -> float:
    result = run_capture(
        [
            ffmpeg_path(),
            "-hide_banner",
            "-i",
            str(path),
        ]
    )
    text = (result.stderr or "") + "\n" + (result.stdout or "")
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if match:
        hours, minutes, seconds = match.groups()
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return 0.0


def validate_av_sync(path: Path) -> None:
    video_duration = probe_stream_duration(path, "v:0")
    audio_duration = probe_stream_duration(path, "a:0")
    if not video_duration:
        video_duration = probe_format_duration(path)
    if not audio_duration:
        audio_duration = probe_format_duration(path)
    if not video_duration or not audio_duration:
        print("[aviso] Nao consegui validar duracao de audio/video.")
        return
    diff = abs(video_duration - audio_duration)
    if diff > 0.35:
        print(f"[aviso] Possivel problema de sincronia: video={video_duration:.2f}s audio={audio_duration:.2f}s diferenca={diff:.2f}s")
    else:
        print(f"Sincronia OK: diferenca audio/video {diff:.2f}s")


def probe_format_duration(path: Path) -> float:
    return probe_stream_duration(path, "")


def slugify(value: str) -> str:
    clean = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
    while "--" in clean:
        clean = clean.replace("--", "-")
    return clean.strip("-")[:70] or "corte"


def escape_drawtext(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("%", "\\%")
        .replace("\n", " ")
    )


def escape_filter_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def render_size(quality: str) -> tuple[int, int]:
    if quality == "4k":
        return 2160, 3840
    if quality == "alta":
        return 1440, 2560
    return 1080, 1920


def focus_position(focus: str) -> float:
    positions = {
        "left": 0.24,
        "center": 0.50,
        "right": 0.76,
    }
    return positions.get(focus, positions["center"])


def normalize_focus_segment(segment: tuple) -> tuple[float, float, float, float]:
    if len(segment) >= 4:
        start, end, x_pos, y_pos = segment[:4]
    else:
        start, end, x_pos = segment[:3]
        y_pos = 0.42
    return float(start), float(end), float(x_pos), float(y_pos)


def timeline_axis_expression(normalized: list[tuple[float, float, float, float]], axis_index: int) -> str:
    transition_seconds = 1.45
    fallback = f"{normalized[-1][axis_index]:.3f}"
    expression = fallback
    previous_value = normalized[0][axis_index]

    for index, segment in reversed(list(enumerate(normalized))):
        start = segment[0]
        end = segment[1]
        value = segment[axis_index]
        if index > 0:
            previous_value = normalized[index - 1][axis_index]
        transition_end = min(end, start + transition_seconds)
        if index == 0 or abs(value - previous_value) < 0.01 or transition_end <= start + 0.05:
            segment_expression = f"{value:.3f}"
        else:
            segment_expression = (
                f"if(between(t,{start:.2f},{transition_end:.2f}),"
                f"{previous_value:.3f}+({value:.3f}-{previous_value:.3f})*((t-{start:.2f})/{max(transition_end-start,0.05):.2f}),"
                f"{value:.3f})"
            )
        expression = f"if(between(t,{start:.2f},{end:.2f}),{segment_expression},{expression})"
    return expression


def crop_x_expression(focus: str, focus_timeline: list[tuple] | None, wobble: str) -> str:
    def target_expr(x_pos: str, moving: bool) -> str:
        motion = "0" if moving else f"{wobble}*sin(t*1.8)"
        return f"max(0,min(in_w-out_w,in_w*({x_pos})-out_w/2+{motion}))"

    if not focus_timeline:
        return target_expr(f"{focus_position(focus):.3f}", False)

    normalized = [normalize_focus_segment(segment) for segment in focus_timeline]
    return target_expr(timeline_axis_expression(normalized, 2), True)


def crop_y_expression(focus_timeline: list[tuple] | None, wobble: str) -> str:
    def target_expr(y_pos: str, moving: bool) -> str:
        motion = "0" if moving else f"{wobble}*sin(t*1.15)"
        return f"max(0,min(in_h-out_h,in_h*({y_pos})-out_h/2+{motion}))"

    if not focus_timeline:
        return f"(in_h-out_h)/2+{wobble}*sin(t*1.15)"

    normalized = [normalize_focus_segment(segment) for segment in focus_timeline]
    return target_expr(timeline_axis_expression(normalized, 3), True)


def adjust_focus_timeline_for_source_crop(
    focus_timeline: list[tuple[float, float, float]] | None,
    top_crop_ratio: float,
    kept_height_ratio: float,
) -> list[tuple] | None:
    if not focus_timeline:
        return focus_timeline
    adjusted: list[tuple] = []
    for segment in focus_timeline:
        start, end, x_pos, y_pos = normalize_focus_segment(segment)
        adjusted_y = min(0.74, max(0.18, (y_pos - top_crop_ratio) / kept_height_ratio))
        adjusted.append((start, end, x_pos, adjusted_y))
    return adjusted


def build_filter(
    headline: str,
    show_headline: bool = True,
    quality: str = "alta",
    hook: str | None = None,
    show_hook: bool = True,
    focus: str = "center",
    subtitles: Path | None = None,
    motion_style: str = "standard",
    focus_timeline: list[tuple[float, float, float]] | None = None,
    remove_source_text: bool = True,
) -> str:
    width, height = render_size(quality)
    font = "C\\:/Windows/Fonts/segoeuib.ttf"
    safe_headline = escape_drawtext(headline.upper())
    safe_hook = escape_drawtext((hook or "PRESTA ATENCAO NESSE TRECHO").upper())
    crop_move = {
        "calm": ("14", "8"),
        "standard": ("30", "18"),
        "aggressive": ("48", "26"),
    }.get(motion_style, ("30", "18"))

    filters = []
    if remove_source_text:
        # Remove common baked-in podcast text by cropping source borders before the vertical crop.
        top_crop_ratio = 0.06
        kept_height_ratio = 0.80
        filters.append(f"crop=iw:ih*{kept_height_ratio:.2f}:0:ih*{top_crop_ratio:.2f}")
        focus_timeline = adjust_focus_timeline_for_source_crop(focus_timeline, top_crop_ratio, kept_height_ratio)
    filters.extend(
        [
            f"scale={width}:{height}:force_original_aspect_ratio=increase",
            (
                f"crop={width}:{height}:"
                f"x='{crop_x_expression(focus, focus_timeline, crop_move[0])}':"
                f"y='{crop_y_expression(focus_timeline, crop_move[1])}'"
            ),
            "fps=30",
        ]
    )
    filters.extend(
        [
            "eq=contrast=1.06:saturation=1.08:brightness=-0.015",
            "unsharp=5:5:0.45:3:3:0.15",
            "vignette=PI/6",
        ]
    )
    if subtitles and subtitles.exists():
        safe_subtitles = escape_filter_path(subtitles)
        filters.append(
            "subtitles="
            f"'{safe_subtitles}':"
            "force_style='FontName=Segoe UI Semibold,"
            "FontSize=13,"
            "PrimaryColour=&H00FFFFFF&,"
            "OutlineColour=&H00000000&,"
            "BorderStyle=1,"
            "Outline=2,"
            "Shadow=1,"
            "Alignment=2,"
            "MarginV=210'"
        )
    if show_hook:
        filters.extend(
            [
                (
                    f"drawbox=x={int(width * 0.055)}:y={int(height * 0.705)}:"
                    f"w={int(width * 0.89)}:h={int(height * 0.125)}:"
                    "color=black@0.72:t=fill:enable='between(t,0,5)'"
                ),
                (
                    f"drawtext=fontfile='{font}':"
                    f"text='{safe_hook}':"
                    f"x=(w-text_w)/2:y={int(height * 0.728)}:"
                    f"fontsize={int(width * 0.049)}:fontcolor=white:"
                    f"line_spacing={int(width * 0.010)}:"
                    f"borderw={max(3, int(width * 0.003))}:bordercolor=black@0.65:"
                    "enable='between(t,0,5)'"
                ),
            ]
        )
    if show_headline:
        filters.extend(
            [
            f"drawbox=x={int(width * 0.042)}:y={int(height * 0.055)}:w={int(width * 0.916)}:h={int(height * 0.122)}:color=black@0.58:t=fill",
            (
                f"drawtext=fontfile='{font}':"
                f"text='{safe_headline}':"
                f"x=(w-text_w)/2:y={int(height * 0.074)}:"
                f"fontsize={int(width * 0.055)}:fontcolor=white:"
                f"line_spacing={int(width * 0.010)}:borderw={max(3, int(width * 0.003))}:bordercolor=black@0.55"
            ),
            ]
        )
    filters.extend(["setsar=1", "setdar=9/16", "setpts=PTS-STARTPTS", "format=yuv420p"])
    return ",".join(filters)


def _build_hook_preroll(
    main_cut: Path,
    hook_audio: Path,
    hook_text: str,
    duration: float,
    quality: str,
    out_dir: Path,
) -> Path:
    """Render a 3-5s pre-roll: zoomed first frame + TTS audio + bold hook text.

    Returns path to pre-roll MP4 sized identically to the main cut.
    """
    width, height = render_size(quality)
    duration = max(1.5, min(duration + 0.2, 6.5))  # clamp safety
    preroll_path = out_dir / "preroll-hook.mp4"
    safe_text = escape_drawtext(hook_text.upper())
    font = "C\\:/Windows/Fonts/segoeuib.ttf"
    fontsize = int(width * 0.085)

    # Slow Ken Burns on the first frame of the main cut.
    video_filter = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},"
        "zoompan=z='min(zoom+0.0008,1.10)':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={int(duration * 30)}:s={width}x{height}:fps=30,"
        f"drawbox=x=0:y={int(height * 0.42)}:w={width}:h={int(height * 0.18)}:color=black@0.55:t=fill,"
        f"drawtext=fontfile='{font}':text='{safe_text}':"
        f"x=(w-text_w)/2:y={int(height * 0.46)}:"
        f"fontsize={fontsize}:fontcolor=white:"
        f"line_spacing={int(width * 0.012)}:"
        f"borderw={max(4, int(width * 0.004))}:bordercolor=black,"
        "format=yuv420p,setsar=1"
    )

    run_ffmpeg(
        [
            "-ss", "0",
            "-t", "0.1",
            "-i", str(main_cut),
            "-i", str(hook_audio),
            "-filter_complex",
            f"[0:v]loop=loop=-1:size=1:start=0,trim=duration={duration:.2f},{video_filter}[v];"
            f"[1:a]apad,atrim=0:{duration:.2f},loudnorm=I=-14:TP=-1.0[a]",
            "-map", "[v]",
            "-map", "[a]",
            "-t", f"{duration:.2f}",
            *video_encoder_args(VIDEO_CRF, VIDEO_MAXRATE, VIDEO_BUFSIZE),
            "-c:a", "aac",
            "-b:a", "160k",
            "-r", "30",
            "-pix_fmt", "yuv420p",
            str(preroll_path),
        ]
    )
    return preroll_path


def _concat_preroll_with_cut(preroll: Path, main_cut: Path, output: Path) -> None:
    """Concat pre-roll + main cut into output, re-encoding to ensure compat."""
    width, height = (1920, 1920)  # placeholder; main cut already correct size
    list_file = output.parent / "concat-list.txt"
    list_file.write_text(
        f"file '{preroll.resolve().as_posix()}'\nfile '{main_cut.resolve().as_posix()}'\n",
        encoding="utf-8",
    )
    run_ffmpeg(
        [
            "-f", "concat",
            "-safe", "0",
            "-i", str(list_file),
            *video_encoder_args(VIDEO_CRF, VIDEO_MAXRATE, VIDEO_BUFSIZE),
            "-c:a", "aac",
            "-b:a", "160k",
            "-movflags", "+faststart",
            str(output),
        ]
    )
    try:
        list_file.unlink()
    except OSError:
        pass


def _find_vtt_for_source(source: Path) -> Path | None:
    """Search .work/analysis/ for a VTT file matching the source video by ID."""
    import re as _re
    analysis_dir = ROOT / ".work" / "analysis"
    if not analysis_dir.exists():
        return None
    # Extract YouTube video ID from source filename (11-char alphanumeric)
    m = _re.search(r"[-_]([A-Za-z0-9_-]{11})[-_.]", source.name)
    video_id = m.group(1) if m else None

    all_vtts = list(analysis_dir.glob("*.vtt"))
    if video_id:
        # Filter to VTTs containing this video ID
        matching = [p for p in all_vtts if video_id in p.name]
        # Prefer translated (.pt.vtt) over original (.pt-orig.vtt)
        preferred = [p for p in matching if p.name.endswith(".pt.vtt")]
        if preferred:
            return preferred[0]
        if matching:
            return matching[0]

    # Fallback: most recently modified non-orig VTT
    candidates = sorted(all_vtts, key=lambda p: p.stat().st_mtime, reverse=True)
    preferred = [p for p in candidates if p.name.endswith(".pt.vtt")]
    return preferred[0] if preferred else (candidates[0] if candidates else None)


def _start_to_seconds(start: str) -> float:
    """Convert HH:MM:SS or MM:SS string to seconds."""
    parts = start.strip().split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


def _generate_animated_subtitles_for_cut(
    source: Path,
    start: str,
    duration: float,
    out_dir: Path,
    quality: str,
    language: str = "pt",
    model_size: str = "small",
) -> Path | None:
    """Extract audio from cut range, transcribe word-level, return path to ASS file.

    Falls back automatically through: faster-whisper → openai-whisper → YouTube VTT.
    """
    from animated_subtitles import (
        generate_animated_subtitles, SubtitleStyle,
        words_from_vtt, words_to_ass,
    )

    width, height = render_size(quality)
    ass_path = out_dir / "legendas-animadas.ass"
    clip_start_s = _start_to_seconds(start)

    # Try ML-based transcription first (faster-whisper / openai-whisper)
    audio_temp = out_dir / "audio_for_subs.wav"
    print("[animated-subtitles] extraindo audio do trecho...", flush=True)
    try:
        run_ffmpeg(
            [
                "-ss", start,
                "-i", str(source),
                "-t", f"{duration:.2f}",
                "-vn", "-ac", "1", "-ar", "16000",
                "-c:a", "pcm_s16le",
                str(audio_temp),
            ]
        )
        vtt_fallback = _find_vtt_for_source(source)
        print("[animated-subtitles] transcrevendo...", flush=True)
        generate_animated_subtitles(
            audio_temp,
            ass_path,
            language=language,
            model_size=model_size,
            style=SubtitleStyle(),
            video_width=width,
            video_height=height,
            vtt_path=vtt_fallback,
            clip_start_s=clip_start_s,
            clip_duration_s=duration,
        )
        return ass_path
    except Exception as exc:
        print(f"[animated-subtitles] todos backends falharam: {exc}", flush=True)
        return None
    finally:
        if audio_temp.exists():
            try:
                audio_temp.unlink()
            except OSError:
                pass


def create_cut(
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
    silent: bool = False,
) -> Path:
    if not source.exists():
        raise FileNotFoundError(source)

    music_path = music
    use_music = bool(music_path and music_path.exists())

    OUTPUTS.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = f"-{slugify(variant_name)}" if variant_name else ""
    out_dir = output_dir or OUTPUTS / f"{stamp}-corte-{slugify(headline)}{suffix}"
    out_dir.mkdir(parents=True, exist_ok=True)

    output_name = {
        "4k": "corte-vertical-4k.mp4",
        "alta": "corte-vertical-alta.mp4",
        "tiktok": "corte-vertical-tiktok.mp4",
    }[quality]
    output = out_dir / output_name
    temp_output = out_dir / "renderizando.tmp.mp4"
    if temp_output.exists():
        temp_output.unlink()

    if animated_subtitles and not subtitles:
        generated = _generate_animated_subtitles_for_cut(
            source, start, duration, out_dir, quality
        )
        if generated and generated.exists():
            subtitles = generated

    base_args = ["-ss", start, "-i", str(source)]
    if use_music:
        base_args.extend(["-stream_loop", "-1", "-i", str(music_path)])
    duration_args = ["-t", f"{duration:.2f}"]

    video_filter = build_filter(
        headline,
        show_headline=show_headline,
        quality=quality,
        hook=hook,
        show_hook=show_hook,
        focus=focus,
        subtitles=subtitles,
        motion_style=motion_style,
        focus_timeline=focus_timeline,
        remove_source_text=remove_source_text,
    )
    voice_filter = "asetpts=PTS-STARTPTS,loudnorm=I=-16:LRA=9:TP=-1.5,acompressor=threshold=-18dB:ratio=2.4:attack=6:release=80"

    if use_music:
        ffmpeg_args = [
            *base_args,
            *duration_args,
            "-filter_complex",
            (
                f"[0:v]{video_filter}[v];"
                f"[0:a]{voice_filter}[voice];"
                f"[1:a]volume={music_volume:.3f}[music];"
                "[voice][music]amix=inputs=2:duration=first:dropout_transition=2[a]"
            ),
            "-map",
            "[v]",
            "-map",
            "[a]",
        ]
    else:
        ffmpeg_args = [
            *base_args,
            *duration_args,
            "-vf",
            video_filter,
            "-af",
            voice_filter,
        ]

    run_ffmpeg(
        [
            *ffmpeg_args,
            *video_encoder_args(VIDEO_CRF, VIDEO_MAXRATE, VIDEO_BUFSIZE),
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-movflags",
            "+faststart",
            "-avoid_negative_ts",
            "make_zero",
            "-shortest",
            str(temp_output),
        ],
        silent=silent
    )
    temp_output.replace(output)
    validate_av_sync(output)

    if regenerate_hook:
        try:
            from hook_regeneration import generate_hook
            transcript_for_hook = hook_transcript or f"{headline}. {hook or ''}"
            print("[hook-regen] gerando gancho com IA + TTS...", flush=True)
            result = generate_hook(
                transcript_for_hook,
                out_dir,
                channel_context=headline,
                voice=hook_voice,
            )
            if result.audio_path and result.audio_path.exists() and result.duration_s > 0.5:
                print(
                    f"[hook-regen] {'AI' if result.used_ai else 'heuristica'}: "
                    f"\"{result.text}\" ({result.duration_s:.2f}s)",
                    flush=True,
                )
                preroll = _build_hook_preroll(
                    output, result.audio_path, result.text,
                    result.duration_s, quality, out_dir,
                )
                final_with_hook = out_dir / f"final-{output.name}"
                _concat_preroll_with_cut(preroll, output, final_with_hook)
                # Replace original output with the hooked version.
                output.unlink()
                final_with_hook.replace(output)
                validate_av_sync(output)
            else:
                print("[hook-regen] sem audio valido; mantendo corte original.", flush=True)
        except Exception as exc:
            print(f"[hook-regen] falha (corte original mantido): {exc}", flush=True)

    (out_dir / "publicacao.txt").write_text(
        headline.strip().rstrip(".")
        + "\n\n"
        + "O detalhe parece pequeno, mas muda o jogo. Quem ganha poder com esse movimento?\n"
        + "#poderemjogo #poder #negocios #ia #economia\n",
        encoding="utf-8",
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Cria um corte vertical 4K a partir de um video-fonte local.")
    parser.add_argument("--source", required=True, help="Caminho do video longo no laptop.")
    parser.add_argument("--start", default="00:00:00", help="Inicio do trecho, ex: 00:12:34.")
    parser.add_argument("--duration", type=float, default=75.0, help="Duracao em segundos.")
    parser.add_argument("--headline", required=True, help="Frase curta que aparece no inicio.")
    parser.add_argument("--no-headline", action="store_true", help="Nao mostra texto fixo no topo do video.")
    parser.add_argument("--hook", default=None, help="Texto forte exibido nos primeiros 5 segundos.")
    parser.add_argument("--no-hook", action="store_true", help="Nao mostra o gancho visual inicial.")
    parser.add_argument("--music", default=None, help="MP3 de musica de fundo. Padrao: sem musica.")
    parser.add_argument("--music-volume", type=float, default=0.07, help="Volume da musica de fundo, ex: 0.05 a 0.10.")
    parser.add_argument("--focus", choices=["left", "center", "right"], default="center", help="Lado principal do rosto no video original.")
    parser.add_argument("--subtitles", default=None, help="Arquivo SRT/ASS para queimar legenda no video.")
    parser.add_argument("--animated-subtitles", action="store_true", help="Gera legendas animadas word-by-word via faster-whisper (estilo OpusClip/CapCut).")
    parser.add_argument("--regenerate-hook", action="store_true", help="Gera gancho IA (GPT) + narracao Edge-TTS como pre-roll de 3-5s.")
    parser.add_argument("--hook-transcript", default=None, help="Texto-base (transcript) para a IA gerar o gancho. Se ausente, usa headline+hook.")
    parser.add_argument("--hook-voice", default="pt-BR-AntonioNeural", help="Voz Edge-TTS (ex: pt-BR-AntonioNeural, pt-BR-FranciscaNeural).")
    parser.add_argument("--motion-style", choices=["calm", "standard", "aggressive"], default="standard", help="Intensidade do movimento/zoom.")
    parser.add_argument("--quality", choices=["tiktok", "alta", "4k"], default="alta", help="alta=1440x2560 recomendado; tiktok=1080x1920 rapido; 4k=2160x3840 lento.")
    args = parser.parse_args()

    output = create_cut(
        Path(args.source),
        args.start,
        args.duration,
        args.headline,
        show_headline=not args.no_headline,
        hook=args.hook,
        show_hook=not args.no_hook,
        music=Path(args.music) if args.music else None,
        music_volume=args.music_volume,
        focus=args.focus,
        subtitles=Path(args.subtitles) if args.subtitles else None,
        motion_style=args.motion_style,
        quality=args.quality,
        animated_subtitles=args.animated_subtitles,
        regenerate_hook=args.regenerate_hook,
        hook_transcript=args.hook_transcript,
        hook_voice=args.hook_voice,
    )
    print(f"Corte criado: {output}")


if __name__ == "__main__":
    main()
