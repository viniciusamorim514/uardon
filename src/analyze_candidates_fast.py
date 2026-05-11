from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from editorial_judge import judge_candidates, local_editorial_score
from find_viral_moments import Candidate, download_subtitles, parse_vtt, seconds_to_timestamp
from make_best_cut import clean_headline
from tiktok_learning import learned_score


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"


def write_user_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8-sig")


def score_label(score: int) -> str:
    if score >= 85:
        return "alto potencial"
    if score >= 75:
        return "bom teste"
    if score >= 65:
        return "medio"
    return "baixo"


def candidate_decision(score: int) -> str:
    if score >= 85:
        return "APROVAR"
    if score >= 75:
        return "TESTAR"
    return "REJEITAR"


def publication_text(headline: str, rank: int, text: str, score: int) -> str:
    question = "Voce concorda com essa leitura?"
    return (
        f"{headline}\n\n"
        f"{question}\n\n"
        "#poderemjogo #politica #geopolitica #negocios #podcast"
    )


def fast_headline(text: str) -> str:
    words = text.strip().split()
    if not words:
        return "ESSE TRECHO MUDA O JOGO"
    first = " ".join(words[:12])
    return clean_headline(first)


def collapse_repeated_words(text: str) -> str:
    words = text.split()
    if not words:
        return ""
    cleaned: list[str] = []
    i = 0
    while i < len(words):
        removed = False
        for size in range(min(12, (len(words) - i) // 2), 1, -1):
            chunk = words[i : i + size]
            next_chunk = words[i + size : i + size * 2]
            if [w.lower() for w in chunk] == [w.lower() for w in next_chunk]:
                cleaned.extend(chunk)
                i += size * 2
                removed = True
                while i + size <= len(words) and [w.lower() for w in words[i : i + size]] == [w.lower() for w in chunk]:
                    i += size
                break
        if not removed:
            cleaned.append(words[i])
            i += 1
    return " ".join(cleaned)


def fast_score(text: str, opening: str) -> tuple[int, int, str, str]:
    lower = text.lower()
    open_lower = opening.lower()
    score = 45
    hook = 45
    reasons: list[str] = []

    power_terms = [
        "ninguém", "maior", "risco", "problema", "mudança", "dinheiro", "empresa",
        "poder", "política", "china", "estados unidos", "brasil", "mundo", "guerra",
        "crise", "verdade", "por que", "como", "nunca", "sempre", "atenção",
    ]
    hits = [term for term in power_terms if term in lower]
    score += min(28, len(hits) * 4)
    if hits:
        reasons.append("tema forte: " + ", ".join(hits[:5]))

    if any(term in open_lower for term in ["por que", "o que", "como", "isso", "ninguém", "se você", "a verdade"]):
        hook += 22
        score += 10
        reasons.append("abertura com curiosidade")

    word_count = len(text.split())
    if 120 <= word_count <= 230:
        score += 10
        reasons.append("densidade boa de fala")
    elif word_count < 80:
        score -= 12
        reasons.append("pouca fala")

    weak_openings = ["então", "é", "eh", "né", "assim", "cara", "tipo"]
    if any(open_lower.startswith(term + " ") for term in weak_openings):
        hook -= 15
        score -= 8
        reasons.append("inicio com palavra fraca")

    score = max(0, min(100, score))
    hook = max(0, min(100, hook))
    return score, hook, "; ".join(reasons) or "boa combinacao de tema e ritmo", "gancho textual"


def find_fast_candidates(captions: list, min_duration: int, max_duration: int, top: int) -> list[Candidate]:
    candidates: list[Candidate] = []
    if not captions:
        return candidates

    step = max(6, len(captions) // 260)
    for start_idx in range(0, len(captions), step):
        start = captions[start_idx].start
        target_end = start + max_duration
        end_idx = start_idx
        while end_idx + 1 < len(captions) and captions[end_idx].end < target_end:
            end_idx += 1
        end = min(captions[end_idx].end, target_end)
        if end - start < min_duration:
            continue
        window = captions[start_idx : end_idx + 1]
        text = collapse_repeated_words(" ".join(line.text for line in window).strip())
        if len(text.split()) < 70:
            continue
        opening = " ".join(line.text for line in window[: max(1, min(5, len(window)))]).strip()
        score, hook_score, reason, hook_reason = fast_score(text, opening)
        if score < 55 or hook_score < 40:
            continue
        candidates.append(
            Candidate(
                score=score,
                start=start,
                end=end,
                headline=fast_headline(text),
                reason=reason,
                text=text,
                text_score=score,
                hook_score=hook_score,
                hook_reason=hook_reason,
                start_adjustment=0.0,
            )
        )

    candidates.sort(key=lambda item: item.score, reverse=True)
    filtered: list[Candidate] = []
    for candidate in candidates:
        overlaps = any(max(candidate.start, chosen.start) < min(candidate.end, chosen.end) - 20 for chosen in filtered)
        if not overlaps:
            filtered.append(candidate)
        if len(filtered) >= top:
            break
    return filtered


def fallback_short_candidate(captions: list, min_score: int) -> Candidate | None:
    if not captions:
        return None
    start = max(0.0, float(captions[0].start))
    end = max(float(captions[-1].end), start + 8.0)
    text = collapse_repeated_words(" ".join(line.text for line in captions).strip())
    if len(text.split()) < 12:
        return None
    headline = fast_headline(text)
    score = max(60, min_score)
    return Candidate(
        score=score,
        start=start,
        end=end,
        headline=headline,
        reason="fallback para video curto: usando o trecho completo porque nao ha janela longa suficiente",
        text=text,
        text_score=score,
        hook_score=65,
        hook_reason="video curto com gancho direto",
        start_adjustment=0.0,
    )


def write_report(candidates: list, source_url: str) -> Path:
    out_dir = OUTPUTS / "relatorios" / "pre-aprovacao" / datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    data_path = out_dir / "candidatos.json"
    report_path = out_dir / "relatorio-de-aprovacao.md"

    data = {"source": source_url, "source_video": "", "candidates": []}
    lines = [
        "# Relatorio de aprovacao dos cortes\n\n",
        f"Fonte: {source_url}\n\n",
        "Modo rapido: analisado por transcricao. O video-fonte sera baixado apenas ao renderizar.\n\n",
    ]

    for rank, candidate in enumerate(candidates, start=1):
        start = seconds_to_timestamp(candidate.start)
        duration = int(candidate.end - candidate.start)
        headline = clean_headline(candidate.headline)
        score = int(candidate.score)
        publish_copy = publication_text(headline, rank, candidate.text, score)
        preview_text = candidate.text[:900].strip()
        item = {
            "rank": rank,
            "score": score,
            "classification": score_label(score),
            "decision": candidate_decision(score),
            "start": start,
            "duration": duration,
            "headline": headline,
            "hook_score": int(getattr(candidate, "hook_score", 0)),
            "hook_reason": getattr(candidate, "hook_reason", ""),
            "editorial_score": int(getattr(candidate, "editorial_score", 0)),
            "editorial_reason": getattr(candidate, "editorial_reason", ""),
            "channel_score": int(getattr(candidate, "channel_score", 0)),
            "channel_reason": getattr(candidate, "channel_reason", ""),
            "reason": getattr(candidate, "reason", ""),
            "frame": "",
            "publication": publish_copy,
            "preview": preview_text,
        }
        data["candidates"].append(item)
        lines.extend(
            [
                f"## {rank}. Score {score}/100 - {score_label(score)}\n\n",
                f"Decisao: **{candidate_decision(score)}**\n\n",
                f"Inicio: `{start}` | Duracao: `{duration}s`\n\n",
                f"Titulo sugerido: **{headline}**\n\n",
                f"Score do canal: `{item['channel_score']:+d}` - {item['channel_reason']}\n\n",
                f"Motivo: {item['reason']}\n\n",
                "Descricao pronta:\n\n```text\n",
                publish_copy,
                "\n```\n\n",
                f"> {preview_text}\n\n",
            ]
        )

    data_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    write_user_text(report_path, "".join(lines))
    return report_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Analise rapida de candidatos sem baixar video bruto.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--min-score", type=int, default=75)
    parser.add_argument("--min-duration", type=int, default=60)
    parser.add_argument("--max-duration", type=int, default=90)
    parser.add_argument("--editorial-ai", choices=["auto", "off", "required"], default="auto")
    parser.add_argument("--ai-model", default=None)
    parser.add_argument("--lang", default="pt-orig,pt")
    args = parser.parse_args()

    print("1/4 Baixando transcricao...")
    subtitles = download_subtitles(args.url, args.lang)
    captions = parse_vtt(subtitles)

    print("2/4 Calculando candidatos...")
    pool_size = max(args.count * 2, args.count, 12)
    candidates = find_fast_candidates(captions, args.min_duration, args.max_duration, pool_size)

    print("3/4 Avaliando contexto editorial...")
    if args.editorial_ai != "off":
        candidates = judge_candidates(
            candidates,
            enabled=True,
            require_ai=args.editorial_ai == "required",
            model=args.ai_model,
        )
    else:
        for candidate in candidates:
            editorial_score, editorial_reason, title = local_editorial_score(candidate)
            candidate.editorial_score = editorial_score
            candidate.editorial_reason = "local: " + editorial_reason
            channel_score, channel_reason = learned_score(
                candidate.text,
                " ".join(candidate.text.split()[:38]).lower(),
                max(0.0, candidate.end - candidate.start),
            )
            candidate.channel_score = channel_score
            candidate.channel_reason = channel_reason
            candidate.headline = title
            candidate.score = round(candidate.score * 0.55 + editorial_score * 0.45)
        candidates.sort(key=lambda item: item.score, reverse=True)

    candidates = [item for item in candidates if item.score >= args.min_score][: args.count]
    if not candidates:
        fallback = fallback_short_candidate(captions, args.min_score)
        if not fallback:
            raise RuntimeError("Nenhum candidato passou no score minimo.")
        candidates = [fallback]

    print("4/4 Salvando pre-aprovacao...")
    report = write_report(candidates, args.url)
    print(f"Relatorio de aprovacao: {report}")
    print("Previa pronta.")


if __name__ == "__main__":
    main()
