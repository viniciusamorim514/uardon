from __future__ import annotations

import argparse
import json
from pathlib import Path

from create_cut_from_source import create_cut
from make_best_cut import clean_headline
from youtube_to_cut import download_youtube


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT / "outputs" / "viral-moments" / "candidatos-virais.json"


def safe_score(candidate: dict) -> int:
    return max(0, min(100, int(candidate.get("score", 0))))


def score_label(score: int) -> str:
    if score >= 85:
        return "muito-alto"
    if score >= 70:
        return "alto"
    if score >= 55:
        return "medio"
    if score >= 40:
        return "baixo"
    return "ruim"


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera varios cortes a partir dos candidatos mais virais do relatorio.")
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--count", type=int, default=3, help="Quantidade de cortes para gerar.")
    parser.add_argument("--min-score", type=int, default=60, help="Score minimo de 0 a 100.")
    parser.add_argument("--no-headline", action="store_true", help="Nao mostra texto fixo no topo dos videos.")
    parser.add_argument("--quality", choices=["tiktok", "alta", "4k"], default="alta", help="alta=1440x2560 recomendado; tiktok=1080x1920 rapido; 4k=2160x3840 lento.")
    parser.add_argument("--hook", default=None, help="Texto forte exibido nos primeiros 5 segundos.")
    parser.add_argument("--no-hook", action="store_true", help="Nao mostra o gancho visual inicial.")
    parser.add_argument("--music", default=None, help="MP3 de musica de fundo. Padrao: sem musica.")
    parser.add_argument("--music-volume", type=float, default=0.07, help="Volume da musica de fundo, ex: 0.05 a 0.10.")
    parser.add_argument("--focus", choices=["left", "center", "right"], default="center", help="Lado principal do rosto no video original.")
    args = parser.parse_args()

    data = json.loads(Path(args.report).read_text(encoding="utf-8"))
    url = data["source"]
    candidates = [
        candidate
        for candidate in data["candidates"]
        if safe_score(candidate) >= args.min_score
    ][: args.count]

    if not candidates:
        raise RuntimeError("Nenhum candidato atingiu o score minimo escolhido.")

    print(f"Baixando video uma vez: {url}")
    source = download_youtube(url)

    created: list[Path] = []
    for index, candidate in enumerate(candidates, start=1):
        score = safe_score(candidate)
        start = candidate["start"]
        duration = float(candidate["duration"])
        headline = clean_headline(candidate["headline"])
        print(f"\nCorte {index}/{len(candidates)} | score={score}/100 ({score_label(score)}) | inicio={start}")
        try:
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
        except Exception as exc:
            print(f"[erro] Nao consegui criar o corte {index}: {exc}")
            continue
        created.append(output)

        metadata = output.with_name("score-viral.txt")
        metadata.write_text(
            "\n".join(
                [
                    f"score={score}/100",
                    f"classificacao={score_label(score)}",
                    f"inicio={start}",
                    f"duracao={int(duration)}",
                    f"headline={headline}",
                    f"motivo={candidate.get('reason', '')}",
                    f"fonte={url}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    print("\nCortes criados:")
    for output in created:
        print(output)


if __name__ == "__main__":
    main()
