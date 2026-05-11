from __future__ import annotations

import json
import os
import re
from dataclasses import replace
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from channel_profile import channel_prompt_context
from find_viral_moments import (
    Candidate,
    editorial_title,
    is_commercial_candidate,
    seconds_to_timestamp,
    thesis_score,
    weak_chatter_score,
)
from make_best_cut import clean_headline
from tiktok_learning import learned_score


ROOT = Path(__file__).resolve().parents[1]


SYSTEM_PROMPT = f"""
Voce e o editor-chefe do canal Poder em Jogo e trabalha como avaliador de cortes virais para TikTok/Reels.
{channel_prompt_context()}

Objetivo: escolher trechos que prendem nos primeiros 5 segundos, geram comentario e fazem sentido sem contexto externo.
Seja rigoroso. Nao aprove trecho so porque tem voz alta, nome famoso, frase solta, polemica vazia ou palavra forte.

Avalie cada candidato como um editor profissional, seguindo este checklist:
1. Gancho: o primeiro pensamento do trecho cria curiosidade imediata?
2. Clareza: uma pessoa que caiu no video agora entende o assunto?
3. Conflito: existe tensao, contraste, risco, erro, disputa ou consequencia?
4. Progressao: o trecho anda para algum lugar ou fica repetindo a mesma ideia?
5. Comentabilidade: da vontade de concordar, discordar ou completar nos comentarios?
6. Canal: combina com poder, dinheiro, IA, negocios, economia, geopolitica ou decisoes que mudam o jogo?
7. Corte: o trecho funciona sozinho em 30-90 segundos?
8. Risco: parece propaganda, bastidor interno, motivacional generico ou conversa sem consequencia?

Penalize forte:
- inicio com "entao", "tipo", "cara", "ne", "isso", "a gente" sem contexto claro
- candidato que depende de algo dito antes
- trecho comercial, jabá, chamada de curso, produto ou evento
- frase bonita sem tese
- candidato sem fechamento ou sem curiosidade para o proximo pensamento

Titulo:
- maximo 70 caracteres
- natural, direto e especifico
- sem clickbait vazio
- sem parecer legenda cortada
- nao use aspas

Se estiver incerto, reduza a nota. Retorne somente JSON valido.
""".strip()


def has_api_key() -> bool:
    load_dotenv(ROOT / ".env")
    return bool(os.getenv("OPENAI_API_KEY"))


def compact_text(text: str, limit: int = 1800) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "..."


def fallback_title(text: str, headline: str) -> str:
    title = editorial_title(text, headline)
    if title:
        return title
    clean = clean_headline(headline).strip().rstrip(".")
    text_lower = text.lower()
    if "produtividade" in text_lower and ("inflacao" in text_lower or "inflação" in text_lower):
        return "A PRODUTIVIDADE MUDA O JOGO DA INFLACAO"
    if "inteligencia artificial" in text_lower or "inteligência artificial" in text_lower or " ia " in f" {text_lower} ":
        return "A IA PODE QUEBRAR EMPRESAS DESATENTAS"
    if "dinheiro" in text_lower:
        return "ISSO NAO E SO SOBRE DINHEIRO"
    if "empresa" in text_lower or "negocio" in text_lower:
        return "SUA EMPRESA PODE FICAR PARA TRAS"
    if "verdade" in text_lower:
        return "A VERDADE QUE POUCA GENTE FALA"
    return clean[:58].rsplit(" ", 1)[0].upper() or "ESSE DETALHE MUDA TUDO"


def local_editorial_score(candidate: Candidate, include_learning: bool = True) -> tuple[int, str, str]:
    text = candidate.text
    lower = text.lower()
    words = text.split()
    opening = " ".join(words[:38]).lower()
    closing = " ".join(words[-42:]).lower()
    score = 40
    reasons: list[str] = []

    weak_opening = bool(
        re.match(
            r"^(e|é|eh|né|então|entao|cara|tipo|deles|dele|dela|eles|elas|isso|aquilo|que|porque)[,;:\s]",
            opening,
        )
    )

    is_ad, ad_reason = is_commercial_candidate(text, opening)
    thesis_bonus, thesis_reason = thesis_score(text, opening)
    chatter_penalty, chatter_reason = weak_chatter_score(text, opening)
    duration_s = max(0.0, candidate.end - candidate.start)
    learning_bonus, learning_reason = learned_score(text, opening, duration_s)

    if 70 <= len(words) <= 150:
        score += 12
        reasons.append("tamanho bom")
    elif 151 <= len(words) <= 190:
        score += 6
        reasons.append("tamanho aceitavel")
    if any(term in lower for term in ["mas", "so que", "na verdade", "o problema", "o ponto"]):
        score += 14
        reasons.append("tem contraste")
    if any(term in opening for term in ["mas", "so que", "na verdade", "o problema", "o ponto", "voce", "você"]):
        score += 12
        reasons.append("começa com tensao")
    if weak_opening:
        score -= 22
        reasons.append("inicio solto")
    else:
        score += 10
        reasons.append("inicio independente")
    if is_ad:
        score -= 80
        reasons.append(ad_reason)
    if thesis_bonus:
        score += min(32, thesis_bonus)
        reasons.append("tese forte: " + thesis_reason)
    if chatter_penalty:
        score -= min(35, chatter_penalty)
        reasons.append(chatter_reason)
    if include_learning and learning_bonus:
        score += learning_bonus
        reasons.append(learning_reason)
    if any(term in opening for term in ["empresa", "negocio", "negócio", "ia", "inteligencia artificial", "inteligência artificial", "dinheiro", "poder", "produtividade"]):
        score += 10
        reasons.append("contexto claro cedo")
    if "?" in text:
        score += 8
        reasons.append("abre pergunta")
    if any(term in lower for term in ["dinheiro", "poder", "empresa", "erro", "verdade", "medo", "risco", "inflacao", "inflação", "produtividade"]):
        score += 12
        reasons.append("tema comentavel")
    if any(term in closing for term in ["por isso", "entao", "então", "ou seja", "conclusao", "conclusão", "resultado", "consequencia", "consequência"]):
        score += 8
        reasons.append("tem fechamento")
    if len(words) < 55:
        score -= 12
        reasons.append("pouco contexto")
    if len(words) > 230:
        score -= 10
        reasons.append("longo demais")

    title = fallback_title(text, candidate.headline)
    return max(0, min(100, score)), ", ".join(reasons) or "analise editorial local", title


def build_user_prompt(candidates: list[Candidate]) -> str:
    payload = []
    for index, candidate in enumerate(candidates, start=1):
        words = candidate.text.split()
        payload.append(
            {
                "id": index,
                "start": seconds_to_timestamp(candidate.start),
                "duration": int(candidate.end - candidate.start),
                "current_score": candidate.score,
                "hook_score": candidate.hook_score,
                "hook_reason": candidate.hook_reason,
                "current_headline": candidate.headline,
                "first_words": compact_text(" ".join(words[:45]), 420),
                "last_words": compact_text(" ".join(words[-45:]), 420),
                "transcript": compact_text(candidate.text),
            }
        )
    return (
        "Tarefa: avaliar candidatos de cortes para o canal Poder em Jogo.\n"
        "Compare os candidatos entre si e seja seletivo. Nota 80+ deve ser rara.\n"
        "Use first_words para julgar o gancho inicial e last_words para julgar fechamento.\n\n"
        "Retorne JSON exatamente neste formato:\n"
        '{"items":[{"id":1,"editorial_score":0,"title":"TITULO CURTO",'
        '"reason":"motivo curto e especifico","comment_question":"pergunta curta"}]}\n\n'
        + json.dumps(payload, ensure_ascii=False)
    )


def ai_evaluate(candidates: list[Candidate], model: str) -> dict[int, dict]:
    client = OpenAI()
    response = client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(candidates)},
        ],
    )
    content = response.choices[0].message.content or "{}"
    data = json.loads(content)
    items = data.get("items", [])
    return {int(item["id"]): item for item in items if "id" in item}


def judge_candidates(
    candidates: list[Candidate],
    enabled: bool = True,
    require_ai: bool = False,
    model: str | None = None,
) -> list[Candidate]:
    if not enabled:
        return candidates

    model = model or os.getenv("OPENAI_MODEL") or "gpt-4.1-mini"
    evaluations: dict[int, dict] = {}
    used_ai = False

    if has_api_key():
        try:
            evaluations = ai_evaluate(candidates, model)
            used_ai = True
        except Exception as exc:
            if require_ai:
                raise RuntimeError(f"Avaliacao editorial por IA falhou: {exc}") from exc
            print(f"[aviso] IA editorial falhou; usando avaliacao local. Motivo: {exc}")
    elif require_ai:
        raise RuntimeError("OPENAI_API_KEY nao configurada. Defina a chave ou use --editorial-ai auto/off.")

    judged: list[Candidate] = []
    for index, candidate in enumerate(candidates, start=1):
        item = evaluations.get(index)
        opening = " ".join(candidate.text.split()[:38]).lower()
        duration_s = max(0.0, candidate.end - candidate.start)
        learning_bonus, learning_reason = learned_score(candidate.text, opening, duration_s)
        if item:
            editorial_score = max(0, min(100, int(item.get("editorial_score", 0))))
            title = clean_headline(str(item.get("title") or candidate.headline)).upper()
            reason = str(item.get("reason") or "avaliado por IA")
        else:
            editorial_score, reason, title = local_editorial_score(candidate, include_learning=False)

        final_score = round(candidate.score * 0.45 + editorial_score * 0.55 + learning_bonus)
        full_reason = reason
        if learning_bonus:
            full_reason = f"{reason}, canal: {learning_reason}"
        judged.append(
            replace(
                candidate,
                score=max(0, min(100, final_score)),
                headline=title,
                editorial_score=editorial_score,
                editorial_reason=("IA: " if used_ai and item else "local: ") + full_reason,
                channel_score=learning_bonus,
                channel_reason=learning_reason,
                reason=f"{candidate.reason}; editorial: {full_reason}",
            )
        )

    judged.sort(key=lambda item: item.score, reverse=True)
    return judged
