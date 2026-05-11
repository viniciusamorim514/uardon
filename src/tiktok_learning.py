from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEARNING_PATH = ROOT / "outputs" / "tiktok-analytics" / "aprendizado.json"
ANALYTICS_PATH = ROOT / "analytics.csv"
_LEARNING_CHECKED = False


DEFAULT_RULES = {
    "positive_terms": ["ia", "negocios", "empresa", "empreendedorismo", "tecnologia"],
    "watch_terms": ["cenario", "hipotetico", "jogo", "mudaria"],
    "weak_terms": ["poder global"],
    "recommended_duration": "45-70s",
}

BLOCKED_TERMS = {
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
    "pode",
    "estar",
    "anos",
    "maior",
    "proximos",
    "nos",
    "sua",
    "ter",
    "nao",
    "video",
    "corte",
}


def normalize(text: str) -> str:
    text = (text or "").lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-z0-9# ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def load_learning() -> dict:
    global _LEARNING_CHECKED
    if not _LEARNING_CHECKED:
        _LEARNING_CHECKED = True
        try:
            needs_refresh = ANALYTICS_PATH.exists() and (
                not LEARNING_PATH.exists() or ANALYTICS_PATH.stat().st_mtime > LEARNING_PATH.stat().st_mtime
            )
            if needs_refresh:
                from analyze_tiktok_metrics import analyze

                analyze()
        except Exception as exc:
            print(f"[aviso] Nao consegui atualizar aprendizado do TikTok: {exc}")
    if not LEARNING_PATH.exists():
        return {"learned_rules": DEFAULT_RULES, "videos": []}
    try:
        return json.loads(LEARNING_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"learned_rules": DEFAULT_RULES, "videos": []}


def learned_terms() -> tuple[list[str], list[str], list[str]]:
    data = load_learning()
    rules = data.get("learned_rules", {})
    positive = [normalize(item) for item in rules.get("prioritize_angles", []) if normalize(item)]
    positive.extend(normalize(item) for item in rules.get("positive_terms", []) if normalize(item))
    hashtags = [normalize(item).lstrip("#") for item in rules.get("prioritize_hashtags", []) if normalize(item)]
    positive.extend(hashtags)
    watch = [normalize(item) for item in rules.get("retention_terms", []) if normalize(item)]
    weak = [normalize(item) for item in rules.get("weak_terms", []) if normalize(item)]

    videos = data.get("videos", [])
    strong_videos = [item for item in videos if int(item.get("score", 0) or 0) >= 45]
    weak_videos = [item for item in videos if int(item.get("score", 0) or 0) <= 40]

    for item in strong_videos:
        positive.extend(tokenize(item.get("tema", "")))
        positive.extend(tokenize(item.get("gancho", "")))
    for item in strong_videos:
        if float(item.get("completion_pct", 0) or 0) >= 5 or float(item.get("retention_pct", 0) or 0) >= 45:
            watch.extend(tokenize(item.get("tema", "")))
            watch.extend(tokenize(item.get("gancho", "")))

    for item in weak_videos:
        weak.extend(extract_phrases(item.get("tema", "")))
        weak.extend(extract_phrases(item.get("gancho", "")))

    positive.extend(DEFAULT_RULES["positive_terms"])
    watch.extend(DEFAULT_RULES["watch_terms"])
    weak.extend(DEFAULT_RULES["weak_terms"])
    positive_terms = unique_terms(positive)
    watch_terms = unique_terms(watch)
    protected = set(positive_terms) | set(watch_terms)
    weak_terms = [term for term in unique_terms(weak) if term not in protected]
    return positive_terms, watch_terms, weak_terms


def channel_targets() -> dict[str, float]:
    data = load_learning()
    videos = data.get("videos", [])
    if not videos:
        return {"best_completion": 5.0, "best_engagement": 0.04, "best_follow": 0.001, "ideal_min": 45, "ideal_max": 70}

    best = sorted(videos, key=lambda item: int(item.get("score", 0) or 0), reverse=True)[:3]
    completion = [float(item.get("completion_pct", 0) or 0) for item in best]
    engagement = [float(item.get("engagement_rate", 0) or 0) for item in best]
    follow = [float(item.get("follow_rate", 0) or 0) for item in best]
    return {
        "best_completion": max(3.0, sum(completion) / max(1, len(completion))),
        "best_engagement": max(0.02, sum(engagement) / max(1, len(engagement))),
        "best_follow": max(0.0005, sum(follow) / max(1, len(follow))),
        "ideal_min": 45,
        "ideal_max": 70,
    }


def tokenize(text: str) -> list[str]:
    return [word for word in re.findall(r"[a-z0-9]{3,}", normalize(text)) if word not in BLOCKED_TERMS]


def extract_phrases(text: str) -> list[str]:
    normalized = normalize(text)
    words = tokenize(normalized)
    phrases = []
    if normalized:
        phrases.append(normalized)
    phrases.extend(words)
    return phrases


def unique_terms(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for term in terms:
        term = normalize(term).lstrip("#")
        if len(term) < 3 or term in seen or term in BLOCKED_TERMS:
            continue
        seen.add(term)
        result.append(term)
    return result


def learned_score(text: str, opening_text: str = "", duration_s: float | None = None) -> tuple[int, str]:
    body = normalize(text)
    opening = normalize(opening_text)
    positive, watch, weak = learned_terms()
    targets = channel_targets()

    score = 0
    reasons: list[str] = []

    positive_hits = [term for term in positive if term in body][:5]
    opening_hits = [term for term in positive if term in opening][:4]
    watch_hits = [term for term in watch if term in body][:4]
    weak_hits = [term for term in weak if term in body][:4]

    if positive_hits:
        bonus = min(12, len(positive_hits) * 3)
        score += bonus
        reasons.append("aprendizado TikTok favorece: " + ", ".join(positive_hits))
    if opening_hits:
        bonus = min(10, len(opening_hits) * 4)
        score += bonus
        reasons.append("gancho combina com videos melhores: " + ", ".join(opening_hits))
    if watch_hits:
        bonus = min(8, len(watch_hits) * 3)
        score += bonus
        reasons.append("tema com melhor retencao anterior: " + ", ".join(watch_hits))
    if weak_hits:
        penalty = min(12, len(weak_hits) * 4)
        score -= penalty
        reasons.append("tema exigiu gancho mais forte antes: " + ", ".join(weak_hits))

    if duration_s is not None:
        ideal_min = targets["ideal_min"]
        ideal_max = targets["ideal_max"]
        if ideal_min <= duration_s <= ideal_max:
            score += 6
            reasons.append(f"duracao alinhada ao canal ({int(ideal_min)}-{int(ideal_max)}s)")
        elif duration_s < 35:
            score -= 4
            reasons.append("duracao curta demais para desenvolver contexto")
        elif duration_s > 75:
            score -= 10
            reasons.append("duracao longa para a retencao atual")

    if opening_hits and targets["best_engagement"] >= 0.04:
        score += 3
        reasons.append("gancho parecido com video que gerou curtida por view")
    if positive_hits and targets["best_follow"] >= 0.001:
        score += 3
        reasons.append("tema parecido com video que trouxe seguidor")
    if watch_hits and targets["best_completion"] >= 5:
        score += 3
        reasons.append("padrao parecido com melhor conclusao do canal")

    return max(-20, min(25, score)), ", ".join(reasons) or "sem aprendizado aplicavel"
