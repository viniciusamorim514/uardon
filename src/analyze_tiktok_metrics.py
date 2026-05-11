from __future__ import annotations

import csv
import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ANALYTICS = ROOT / "analytics.csv"
OUT_DIR = ROOT / "outputs" / "tiktok-analytics"


@dataclass
class VideoMetric:
    row: dict[str, str]
    views: int
    engagement_rate: float
    follow_rate: float
    retention_pct: float
    completion_pct: float
    avg_watch_s: float
    duration_s: float
    performance_score: int


def to_float(value: str) -> float:
    value = (value or "").strip().replace("%", "").replace(",", ".")
    if not value:
        return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def to_int(value: str) -> int:
    value = (value or "").strip().lower().replace(".", "").replace(",", ".")
    if not value:
        return 0
    multiplier = 1
    if value.endswith("k"):
        multiplier = 1000
        value = value[:-1]
    elif value.endswith("m"):
        multiplier = 1_000_000
        value = value[:-1]
    try:
        return int(float(value) * multiplier)
    except ValueError:
        return 0


def hashtag_tokens(value: str) -> list[str]:
    return [item.lower() for item in re.findall(r"#[\wÀ-ÿ]+", value or "")]


def topic_tokens(value: str) -> list[str]:
    value = (value or "").lower()
    words = re.findall(r"[a-zà-ÿ0-9]{3,}", value)
    blocked = {
        "para",
        "com",
        "que",
        "uma",
        "por",
        "dos",
        "das",
        "isso",
        "esse",
        "essa",
        "video",
        "corte",
        "pode",
        "estar",
        "anos",
        "maior",
        "proximos",
        "sobre",
        "como",
        "quem",
        "usar",
        "ficar",
        "tras",
        "revelou",
        "nos",
        "sua",
        "ter",
        "nao",
    }
    return [word for word in words if word not in blocked]


def score_row(row: dict[str, str]) -> VideoMetric:
    views = max(to_int(row.get("views_7d", "")), to_int(row.get("views_24h", "")), to_int(row.get("views_1h", "")))
    likes = to_int(row.get("curtidas", ""))
    comments = to_int(row.get("comentarios", ""))
    shares = to_int(row.get("compartilhamentos", ""))
    saves = to_int(row.get("salvamentos", ""))
    followers = to_int(row.get("seguidores_ganhos", ""))
    retention_pct = to_float(row.get("retencao_media_pct", ""))
    completion_pct = to_float(row.get("assistiu_completo_pct", ""))
    avg_watch_s = to_float(row.get("tempo_medio_s", ""))
    duration_s = to_float(row.get("duracao_s", ""))

    engagement_rate = (likes + comments * 2 + shares * 3 + saves * 3) / max(views, 1)
    follow_rate = followers / max(views, 1)
    watch_ratio = avg_watch_s / duration_s if duration_s > 0 else retention_pct / 100
    effective_retention_pct = max(retention_pct, watch_ratio * 100)

    score = 0
    score += min(30, math.log10(max(views, 1)) * 8)
    score += min(25, engagement_rate * 600)
    score += min(20, effective_retention_pct * 0.20)
    score += min(15, completion_pct * 0.15)
    score += min(10, follow_rate * 2500)
    performance_score = max(0, min(100, round(score)))

    return VideoMetric(
        row=row,
        views=views,
        engagement_rate=engagement_rate,
        follow_rate=follow_rate,
        retention_pct=round(effective_retention_pct, 2),
        completion_pct=completion_pct,
        avg_watch_s=avg_watch_s,
        duration_s=duration_s,
        performance_score=performance_score,
    )


def average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def grouped_scores(items: list[VideoMetric], key_fn) -> list[tuple[str, int, float]]:
    groups: dict[str, list[int]] = defaultdict(list)
    for item in items:
        for key in key_fn(item):
            if key:
                groups[key].append(item.performance_score)
    result = [(key, len(scores), average(scores)) for key, scores in groups.items() if len(scores) >= 1]
    return sorted(result, key=lambda item: (item[2], item[1]), reverse=True)


def analyze() -> tuple[Path, Path]:
    if not ANALYTICS.exists():
        raise FileNotFoundError(ANALYTICS)

    rows = list(csv.DictReader(ANALYTICS.open("r", encoding="utf-8-sig", newline="")))
    items = [score_row(row) for row in rows if any((value or "").strip() for value in row.values())]
    if not items:
        raise RuntimeError("analytics.csv ainda nao tem videos preenchidos.")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ranked = sorted(items, key=lambda item: item.performance_score, reverse=True)
    themes = grouped_scores(ranked, lambda item: topic_tokens(item.row.get("tema", "")) + topic_tokens(item.row.get("gancho", "")))
    hashtags = grouped_scores(ranked, lambda item: hashtag_tokens(item.row.get("hashtags", "")))
    hours = grouped_scores(ranked, lambda item: [item.row.get("hora_publicacao", "").strip()[:2]] if item.row.get("hora_publicacao") else [])
    avg_completion = average([item.completion_pct for item in items if item.completion_pct > 0])
    avg_watch = average([item.avg_watch_s for item in items if item.avg_watch_s > 0])
    avg_views = average([item.views for item in items if item.views > 0])
    avg_engagement = average([item.engagement_rate for item in items if item.engagement_rate > 0])
    recommended_duration = "45-60s" if avg_completion and avg_completion < 8 else "60-75s"
    strong_videos = [item for item in ranked if item.performance_score >= 45]
    retention_videos = [item for item in ranked if item.completion_pct >= 5 or item.avg_watch_s >= 8]
    weak_videos = [
        item
        for item in ranked
        if item.performance_score <= 40
        or (
            avg_completion > 0
            and item.completion_pct < avg_completion
            and avg_engagement > 0
            and item.engagement_rate < avg_engagement
        )
    ]
    positive_terms = []
    retention_terms = []
    weak_terms = []
    for item in strong_videos:
        positive_terms.extend(topic_tokens(item.row.get("tema", "")))
        positive_terms.extend(topic_tokens(item.row.get("gancho", "")))
    for item in retention_videos:
        retention_terms.extend(topic_tokens(item.row.get("tema", "")))
        retention_terms.extend(topic_tokens(item.row.get("gancho", "")))
    for item in weak_videos:
        weak_terms.extend(topic_tokens(item.row.get("tema", "")))
        weak_terms.extend(topic_tokens(item.row.get("gancho", "")))

    def top_unique(values: list[str], limit: int) -> list[str]:
        counts: dict[str, int] = defaultdict(int)
        for value in values:
            counts[value] += 1
        return [key for key, _ in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:limit]]

    positive_top = top_unique(positive_terms, 12)
    retention_top = top_unique(retention_terms, 12)
    protected_terms = set(positive_top) | set(retention_top)
    weak_top = [term for term in top_unique(weak_terms, 18) if term not in protected_terms][:12]

    learned_rules = {
        "recommended_duration": recommended_duration,
        "avg_completion_pct": round(avg_completion, 2),
        "avg_watch_s": round(avg_watch, 2),
        "avg_views": round(avg_views, 1),
        "prioritize_angles": [key for key, _, _ in themes[:6]],
        "prioritize_hashtags": [key for key, _, _ in hashtags[:5]],
        "positive_terms": positive_top,
        "retention_terms": retention_top,
        "weak_terms": weak_top,
        "notes": [
            "Conclusao baixa: comece mais direto e teste cortes menores.",
            "Temas de IA/negocios geraram melhor engajamento e seguidor nos prints analisados.",
            "Cenarios hipoteticos tiveram melhor tempo medio e percentual de conclusao.",
            "Poder global trouxe views, mas precisa de gancho inicial mais forte para reter.",
        ],
    }

    json_path = OUT_DIR / "aprendizado.json"
    md_path = OUT_DIR / "aprendizado.md"
    json_path.write_text(
        json.dumps(
            {
                "videos": [
                    {
                        "score": item.performance_score,
                        "tema": item.row.get("tema", ""),
                        "gancho": item.row.get("gancho", ""),
                        "hashtags": item.row.get("hashtags", ""),
                        "arquivo": item.row.get("arquivo_video", ""),
                        "views": item.views,
                        "engagement_rate": round(item.engagement_rate, 4),
                        "retention_pct": item.retention_pct,
                        "completion_pct": item.completion_pct,
                        "avg_watch_s": item.avg_watch_s,
                        "duration_s": item.duration_s,
                        "follow_rate": round(item.follow_rate, 5),
                    }
                    for item in ranked
                ],
                "top_temas": themes[:12],
                "top_hashtags": hashtags[:12],
                "top_horarios": hours[:8],
                "learned_rules": learned_rules,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    best = ranked[:5]
    weak = [
        item
        for item in sorted(items, key=lambda item: (item.completion_pct, item.engagement_rate, item.performance_score))
        if item in weak_videos
    ][:5]
    lines = ["# Aprendizado do TikTok\n\n"]
    lines.append(f"Videos analisados: {len(items)}\n\n")
    lines.append("## Melhores videos\n\n")
    for item in best:
        lines.append(
            f"- Score {item.performance_score}/100 | {item.views} views | "
            f"retencao {item.retention_pct:.1f}% | engajamento {item.engagement_rate*100:.2f}% | "
            f"{item.row.get('tema', 'sem tema')}\n"
        )
    lines.append("\n## Videos mais fracos\n\n")
    for item in weak:
        lines.append(
            f"- Score {item.performance_score}/100 | {item.views} views | "
            f"retencao {item.retention_pct:.1f}% | engajamento {item.engagement_rate*100:.2f}% | "
            f"{item.row.get('tema', 'sem tema')}\n"
        )
    lines.append("\n## Temas que mais pontuaram\n\n")
    for key, count, score in themes[:10]:
        lines.append(f"- {key}: media {score:.1f}/100 em {count} video(s)\n")
    lines.append("\n## Hashtags que mais pontuaram\n\n")
    for key, count, score in hashtags[:10]:
        lines.append(f"- {key}: media {score:.1f}/100 em {count} video(s)\n")
    lines.append("\n## Horarios que mais pontuaram\n\n")
    for key, count, score in hours[:8]:
        lines.append(f"- {key}h: media {score:.1f}/100 em {count} video(s)\n")
    lines.append("\n## Leitura pratica\n\n")
    lines.append(f"- Media de views dos prints: {avg_views:.0f}\n")
    lines.append(f"- Tempo medio assistido: {avg_watch:.2f}s\n")
    lines.append(f"- Assistiu completo: {avg_completion:.2f}%\n")
    lines.append(f"- Duracao recomendada para os proximos testes: {recommended_duration}\n")
    lines.append("- Prioridade de pauta: IA/negocios, cenarios hipoteticos e temas com consequencia clara.\n")
    lines.append("- Evitar por enquanto: cortes longos com abertura lenta e tema amplo demais.\n")
    lines.append("\n## Regras para os proximos cortes\n\n")
    lines.append("- Repita temas e ganchos que aparecem nos melhores videos.\n")
    lines.append("- Evite formatos que aparecem nos videos fracos com baixa retencao.\n")
    lines.append("- Priorize cortes com retencao media acima de 45% e comentarios/compartilhamentos acima da media.\n")
    lines.append("- Se um tema traz seguidores, faca novas variacoes dele antes de trocar de assunto.\n")
    md_path.write_text("".join(lines), encoding="utf-8")
    return md_path, json_path


def main() -> None:
    md_path, json_path = analyze()
    print(f"Relatorio criado: {md_path}")
    print(f"Dados: {json_path}")


if __name__ == "__main__":
    main()
