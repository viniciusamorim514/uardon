from __future__ import annotations

import json
from pathlib import Path

from create_cut_from_source import create_cut
from opus_local import publication_text, write_index


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
WORK_YOUTUBE = ROOT / ".work" / "youtube"
INDEX = OUTPUTS / "opus-local" / "ultimos-cortes.json"


def safe_print(value: object) -> None:
    print(str(value).encode("ascii", errors="ignore").decode("ascii"))


def latest_source() -> Path:
    videos = sorted(WORK_YOUTUBE.glob("*.mp4"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not videos:
        raise RuntimeError("Nao achei video-fonte em .work\\youtube.")
    return videos[0]


def main() -> None:
    data = json.loads(INDEX.read_text(encoding="utf-8"))
    source = latest_source()
    created: list[dict] = []

    safe_print(f"Video-fonte: {source}")
    for item in data["cuts"]:
        safe_print(f"Recriando corte {item['rank']}: {item['start']} ({item['duration']}s)")
        output = create_cut(
            source,
            item["start"],
            float(item["duration"]),
            item["headline"],
            show_headline=False,
            quality="alta",
            hook=None,
            show_hook=False,
            music=None,
            music_volume=0.06,
            focus=item.get("focus", "center"),
            subtitles=None,
        )
        new_item = {**item, "video": str(output)}
        created.append(new_item)
        output.with_name("publicacao.txt").write_text(publication_text(item["headline"], int(item["rank"])), encoding="utf-8")
        output.with_name("score-viral.txt").write_text(
            "\n".join(
                [
                    f"score={item['score']}/100",
                    f"classificacao={item['classification']}",
                    f"inicio={item['start']}",
                    f"duracao={item['duration']}",
                    f"headline={item['headline']}",
                    f"foco={item.get('focus', 'center')}",
                    f"motivo={item['reason']}",
                    f"fonte={data['source']}",
                    "observacao=render limpo sem legenda queimada e sem mensagem inicial",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    index = write_index(created, data["source"])
    safe_print(f"Indice atualizado: {index}")
    safe_print("Cortes limpos:")
    for item in created:
        safe_print(item["video"])


if __name__ == "__main__":
    main()
