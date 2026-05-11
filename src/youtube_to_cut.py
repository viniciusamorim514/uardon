from __future__ import annotations

import argparse
import subprocess
import sys
from shutil import which
from pathlib import Path

import imageio_ffmpeg

from create_cut_from_source import create_cut
from video_probe import probe_video


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".work" / "youtube"
SECTION_WORK = ROOT / ".work" / "youtube_sections"
SECTION_END_PADDING_SECONDS = 12.0


def run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=False)


def find_deno() -> str | None:
    found = which("deno")
    if found:
        return found
    winget_packages = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages"
    if winget_packages.exists():
        matches = sorted(winget_packages.rglob("deno.exe"), key=lambda path: path.stat().st_mtime, reverse=True)
        if matches:
            return str(matches[0])
    return None


def ffmpeg_location() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def timestamp_to_seconds(value: str) -> float:
    parts = value.split(":")
    if len(parts) != 3:
        return 0.0
    hours, minutes, seconds = parts
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def seconds_to_timestamp(value: float) -> str:
    value = max(0.0, float(value))
    hours = int(value // 3600)
    minutes = int((value % 3600) // 60)
    seconds = value % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:05.2f}"


def download_youtube(url: str) -> Path:
    WORK.mkdir(parents=True, exist_ok=True)
    before = {path.resolve() for path in WORK.glob("*.mp4")}
    output_template = str(WORK / "%(title).120s-%(id)s-%(height)sp.%(ext)s")
    deno = find_deno()
    base = [
        sys.executable,
        "-m",
        "yt_dlp",
        "-f",
        (
            "bv*[height<=1080][ext=mp4][vcodec^=avc1]+ba[ext=m4a]/"
            "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/"
            "bv*[height<=1080]+ba/"
            "b[height<=1080][ext=mp4]/"
            "b[height<=720][ext=mp4]/best"
        ),
        "--merge-output-format",
        "mp4",
        "--ffmpeg-location",
        ffmpeg_location(),
        "--no-playlist",
        "-o",
        output_template,
    ]
    if deno:
        base.extend(["--js-runtimes", f"deno:{deno}"])
    public_bypass = [
        *base,
        "--extractor-args",
        "youtube:player_client=android,web_embedded,ios",
        "--user-agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        url,
    ]
    attempts = [
        public_bypass,
        [*base, "--cookies-from-browser", "chrome", url],
        [*base, "--cookies-from-browser", "edge", url],
        [*base, url],
    ]

    last_code = 1
    for command in attempts:
        result = run(command)
        last_code = result.returncode
        videos = sorted(
            [path for path in WORK.glob("*.mp4") if path.resolve() not in before],
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if result.returncode == 0:
            if videos:
                return videos[0]
            existing = sorted(WORK.glob("*.mp4"), key=lambda path: path.stat().st_mtime, reverse=True)
            if existing:
                return existing[0]

    videos = sorted(
        [path for path in WORK.glob("*.mp4") if path.resolve() not in before],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not videos:
        raise RuntimeError(f"Nao consegui baixar o video. Ultimo codigo de erro: {last_code}")
    return videos[0]


def download_youtube_section(url: str, start: str, duration: float) -> Path:
    SECTION_WORK.mkdir(parents=True, exist_ok=True)
    start_seconds = timestamp_to_seconds(start)
    expected_duration = float(duration)
    end = seconds_to_timestamp(start_seconds + expected_duration + SECTION_END_PADDING_SECONDS)
    safe_start = start.replace(":", "-")
    before = {path.resolve() for path in SECTION_WORK.glob("*.mp4")}
    output_template = str(SECTION_WORK / f"%(title).90s-%(id)s-{safe_start}-%(height)sp.%(ext)s")
    deno = find_deno()
    base = [
        sys.executable,
        "-m",
        "yt_dlp",
        "-f",
        (
            "bv*[height<=1080][ext=mp4][vcodec^=avc1]+ba[ext=m4a]/"
            "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/"
            "bv*[height<=1080]+ba/"
            "b[height<=1080][ext=mp4]/"
            "b[height<=720][ext=mp4]/best"
        ),
        "--merge-output-format",
        "mp4",
        "--download-sections",
        f"*{start}-{end}",
        "--force-keyframes-at-cuts",
        "--concurrent-fragments",
        "8",
        "--ffmpeg-location",
        ffmpeg_location(),
        "--no-playlist",
        "-o",
        output_template,
    ]
    if deno:
        base.extend(["--js-runtimes", f"deno:{deno}"])
    attempts = [
        [
            *base,
            "--extractor-args",
            "youtube:player_client=android,web_embedded,ios",
            "--user-agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            url,
        ],
        [*base, "--cookies-from-browser", "chrome", url],
        [*base, "--cookies-from-browser", "edge", url],
        [*base, url],
    ]
    last_code = 1
    for command in attempts:
        result = run(command)
        last_code = result.returncode
        videos = sorted(
            [path for path in SECTION_WORK.glob("*.mp4") if path.resolve() not in before],
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if result.returncode == 0 and videos:
            info = probe_video(videos[0])
            if info.duration >= expected_duration * 0.80:
                return videos[0]
            try:
                videos[0].unlink()
            except OSError:
                pass
            print(
                f"[aviso] Trecho baixado veio curto ({info.duration:.1f}s de {expected_duration:.1f}s). Tentando outro metodo..."
            )
    videos = sorted(
        [path for path in SECTION_WORK.glob("*.mp4") if path.resolve() not in before],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not videos:
        # Fallback: corta direto do video completo local (evita re-download / rate-limit)
        full_videos = sorted(WORK.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
        if full_videos:
            full_video = full_videos[0]
            section_out = SECTION_WORK / f"local_cut-{safe_start}-{int(expected_duration)}s.mp4"
            ffmpeg = ffmpeg_location()
            cmd_cut = [
                ffmpeg, "-y",
                "-ss", str(start_seconds),
                "-i", str(full_video),
                "-t", str(expected_duration + SECTION_END_PADDING_SECONDS),
                "-c", "copy",
                str(section_out),
            ]
            print(f"[fallback] Cortando do video local: {full_video.name} a partir de {start}")
            result_cut = subprocess.run(cmd_cut, check=False)
            if result_cut.returncode == 0 and section_out.exists():
                return section_out
        raise RuntimeError(f"Nao consegui baixar o trecho do video. Ultimo codigo de erro: {last_code}")
    return videos[0]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Baixa um video do YouTube e cria um corte vertical 4K. Use apenas videos seus, licenciados ou com permissao."
    )
    parser.add_argument("--url", required=True, help="URL do video do YouTube.")
    parser.add_argument("--start", required=True, help="Inicio do trecho, ex: 00:12:34.")
    parser.add_argument("--duration", type=float, default=75.0, help="Duracao em segundos.")
    parser.add_argument("--headline", required=True, help="Frase curta para prender nos primeiros segundos.")
    parser.add_argument("--quality", choices=["tiktok", "alta", "4k"], default="alta", help="alta=1440x2560 recomendado; tiktok=1080x1920 rapido; 4k=2160x3840 lento.")
    parser.add_argument("--no-headline", action="store_true", help="Nao mostra texto fixo no topo do video.")
    parser.add_argument("--hook", default=None, help="Texto forte exibido nos primeiros 5 segundos.")
    parser.add_argument("--no-hook", action="store_true", help="Nao mostra o gancho visual inicial.")
    parser.add_argument("--music", default=None, help="MP3 de musica de fundo. Padrao: sem musica.")
    parser.add_argument("--music-volume", type=float, default=0.07, help="Volume da musica de fundo, ex: 0.05 a 0.10.")
    parser.add_argument("--focus", choices=["left", "center", "right"], default="center", help="Lado principal do rosto no video original.")
    args = parser.parse_args()

    source = download_youtube(args.url)
    output = create_cut(
        source,
        args.start,
        args.duration,
        args.headline,
        show_headline=not args.no_headline,
        quality=args.quality,
        hook=args.hook,
        show_hook=not args.no_hook,
        music=Path(args.music) if args.music else None,
        music_volume=args.music_volume,
        focus=args.focus,
    )
    print(f"Video baixado: {source}")
    print(f"Corte criado: {output}")


if __name__ == "__main__":
    main()
