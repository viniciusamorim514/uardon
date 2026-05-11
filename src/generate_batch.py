from __future__ import annotations

import argparse
from pathlib import Path

from create_video import build_script, create_video


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topics-file", default="topics.txt")
    parser.add_argument("--voice", default="pt-BR-ThalitaMultilingualNeural")
    parser.add_argument("--voice-rate", default="-4%")
    parser.add_argument("--voice-pitch", default="+0Hz")
    args = parser.parse_args()

    topics_path = Path(args.topics_file)
    topics = [
        line.strip()
        for line in topics_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    if not topics:
        raise SystemExit(f"Nenhum tema encontrado em {topics_path}")

    for index, topic in enumerate(topics, start=1):
        print(f"[{index}/{len(topics)}] Criando video: {topic}")
        script = build_script(topic)
        output = create_video(script, args.voice, args.voice_rate, args.voice_pitch)
        print(f"    pronto: {output}")


if __name__ == "__main__":
    main()
