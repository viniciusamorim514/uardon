from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = ROOT / "config" / "perfil_canal.json"


DEFAULT_PROFILE = {
    "brand_name": "Poder em Jogo",
    "handle": "@poderemjogo",
    "positioning": "Poder, dinheiro, IA, negocios, economia e geopolitica.",
    "editorial_priorities": ["poder", "dinheiro", "ia", "negocios", "economia", "geopolitica"],
    "avoid": ["propaganda", "bastidor", "inicio sem contexto"],
    "default_hashtags": ["#poderemjogo", "#poder", "#negocios", "#ia", "#economia"],
    "angles": {},
}


def load_channel_profile() -> dict:
    if not PROFILE_PATH.exists():
        return DEFAULT_PROFILE
    try:
        profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return DEFAULT_PROFILE
    merged = DEFAULT_PROFILE | profile
    merged["angles"] = DEFAULT_PROFILE.get("angles", {}) | profile.get("angles", {})
    return merged


def angle_copy(angle: str) -> dict:
    profile = load_channel_profile()
    angles = profile.get("angles", {})
    return angles.get(angle) or angles.get("geral") or {
        "hashtags": profile.get("default_hashtags", DEFAULT_PROFILE["default_hashtags"]),
        "question": "Esse detalhe muda sua leitura do assunto?",
        "support": "O detalhe parece pequeno, mas muda a leitura do jogo.",
    }


def channel_prompt_context() -> str:
    profile = load_channel_profile()
    priorities = ", ".join(profile.get("editorial_priorities", []))
    avoid = ", ".join(profile.get("avoid", []))
    positioning = str(profile.get("positioning", "")).strip().rstrip(".")
    return (
        f"Canal: {profile.get('brand_name')} ({profile.get('handle')}).\n"
        f"Posicionamento: {positioning}.\n"
        f"Priorize: {priorities}.\n"
        f"Evite: {avoid}.\n"
        "A decisao editorial deve favorecer cortes com consequencia clara, disputa, risco, dinheiro, tecnologia ou poder."
    )
