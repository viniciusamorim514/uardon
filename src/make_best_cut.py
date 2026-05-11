from __future__ import annotations

import argparse
import json
from pathlib import Path

from youtube_to_cut import create_cut, download_youtube


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT / "outputs" / "viral-moments" / "candidatos-virais.json"


def clean_headline(value: str) -> str:
    replacements = {
        "PAÃSES": "PAISES",
        "PAÃ­SES": "PAISES",
        "FRANÃ‡A": "FRANCA",
        "VÃƒO": "VAO",
        "NÃƒO": "NAO",
        "FINLÃ‚NDIA": "FINLANDIA",
        "POLÃ”NIA": "POLONIA",
        "ENTÃƒO": "ENTAO",
        "Ã‰": "E",
        "Ã€": "A",
        "Ã‡": "C",
        "Ãƒ": "A",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    value = " ".join(value.split())
    if len(value) > 76:
        value = value[:76].rsplit(" ", 1)[0]
    return value or "O DETALHE QUE MUDA O TABULEIRO"


def main() -> None:
    parser = argparse.ArgumentParser(description="Pega o melhor candidato viral e gera o corte automaticamente.")
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--index", type=int, default=1, help="Numero do candidato no relatorio, comecando em 1.")
    parser.add_argument("--no-headline", action="store_true", help="Nao mostra texto fixo no topo do video.")
    parser.add_argument("--quality", choices=["tiktok", "alta", "4k"], default="alta", help="alta=1440x2560 recomendado; tiktok=1080x1920 rapido; 4k=2160x3840 lento.")
    parser.add_argument("--hook", default=None, help="Texto forte exibido nos primeiros 5 segundos.")
    parser.add_argument("--no-hook", action="store_true", help="Nao mostra o gancho visual inicial.")
    parser.add_argument("--music", default=None, help="MP3 de musica de fundo. Padrao: sem musica.")
    parser.add_argument("--music-volume", type=float, default=0.07, help="Volume da musica de fundo, ex: 0.05 a 0.10.")
    parser.add_argument("--focus", choices=["left", "center", "right"], default="center", help="Lado principal do rosto no video original.")
    args = parser.parse_args()

    data = json.loads(Path(args.report).read_text(encoding="utf-8"))
    candidates = data["candidates"]
    candidate = candidates[args.index - 1]

    url = data["source"]
    start = candidate["start"]
    duration = float(candidate["duration"])
    headline = clean_headline(candidate["headline"])

    print(f"Baixando video: {url}")
    source = download_youtube(url)
    print(f"Gerando corte: inicio={start}, duracao={int(duration)}s, headline={headline}")
    output = create_cut(
        source,
        start,
        duration,
        headline,
        show_headline=not args.no_headline,
        quality=args.quality,
        hook=args.hook,
        show_hook=not args.no_hook,
        music=Path(args.music) if args.music else None,
        music_volume=args.music_volume,
        focus=args.focus,
    )
    print(f"Corte criado: {output}")


if __name__ == "__main__":
    main()
