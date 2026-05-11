"""Generate multiple hook variants for A/B testing.

Instead of generating one hook, generates 3 variants with different
tones/styles so the user can pick the best one for their content.

Variants:
  1. "Bold" - Direct, assertive, confrontational
  2. "Question" - Curiosity-driven, asks a thought-provoking question
  3. "Story" - Narrative hook that sets up a story arc

Usage:
    from hook_variants import generate_hook_variants
    variants = generate_hook_variants("Transcript text here", "Poder em Jogo")
    # Returns 3 HookVariant objects with text, style, and audio paths
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from hook_regeneration import (
    HOOK_VOICE_DEFAULT,
    HOOK_VOICE_FEMALE,
    HOOK_RATE,
    HOOK_PITCH,
    synthesize_hook_audio,
    _probe_audio_duration,
    _heuristic_hook,
)

try:
    from observability import log_event
except ImportError:
    # Fallback if observability not available
    def log_event(*args, **kwargs):
        pass


@dataclass
class HookVariant:
    """A single hook variant."""
    text: str
    style: str  # "bold", "question", "story"
    audio_path: Optional[Path] = None
    duration_s: float = 0.0
    used_ai: bool = False

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "style": self.style,
            "audio_path": str(self.audio_path) if self.audio_path else None,
            "duration_s": self.duration_s,
            "used_ai": self.used_ai,
        }


def _generate_hook_variants_ai(
    transcript: str,
    channel_context: str = "",
    model: Optional[str] = None,
) -> list[Optional[str]]:
    """Generate 3 hook variants via GPT. Returns [bold, question, story] or [None, None, None]."""
    try:
        from openai import OpenAI
    except ImportError:
        return [None, None, None]

    model = model or os.getenv("OPENAI_MODEL") or "gpt-4.1-mini"

    system_prompt = (
        "Voce e um editor de TikTok especializado em ganchos virais para conteudo "
        "de geopolitica, poder e negocios em PT-BR. Sua tarefa: gerar 3 ganchos DIFERENTES "
        "com estilos contrastantes.\n\n"
        "Regras para TODOS os ganchos:\n"
        "- 8 a 15 palavras, NUNCA mais\n"
        "- Sem clickbait barato, mas com tensao real\n"
        "- Sem emojis, sem hashtags\n"
        "- Use linguagem falada, direta, em portugues do Brasil\n\n"
        "ESTILO 1 - BOLD (Direto, assertivo):\n"
        "- Comece com declaracao forte ou numero impactante\n"
        "- Termine com afirmacao confrontacional\n"
        "- Exemplo: 'Isso pode gerar colapso economico'\n\n"
        "ESTILO 2 - QUESTION (Curiosidade):\n"
        "- Formule como pergunta provocativa\n"
        "- Ative curiosidade do espectador\n"
        "- Exemplo: 'Voce sabe o que vem acontecendo nos bastidores?'\n\n"
        "ESTILO 3 - STORY (Narrativo):\n"
        "- Comece com elemento de historia/drama\n"
        "- Configure tensao para proxima frase\n"
        "- Exemplo: 'Essa conversa ninguem esperava'\n\n"
        "Retorne APENAS JSON: {\"bold\": \"hook bold\", \"question\": \"hook question\", \"story\": \"hook story\"}"
    )

    user_prompt = (
        f"Canal: {channel_context or 'Poder em Jogo (geopolitica, poder, negocios)'}\n\n"
        f"Trecho original (primeiros segundos):\n{transcript[:1500]}\n\n"
        "Gere 3 ganchos diferentes conforme as regras acima."
    )

    try:
        client = OpenAI()
        response = client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            temperature=0.8,  # Higher temp for more variety
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = response.choices[0].message.content or "{}"
        data = json.loads(content)

        variants = []
        for style in ["bold", "question", "story"]:
            hook = (data.get(style) or "").strip()
            if 4 <= len(hook.split()) <= 22:
                variants.append(hook)
            else:
                variants.append(None)
        return variants

    except Exception as exc:
        print(f"[hook-variants] GPT falhou: {exc}", flush=True)
        return [None, None, None]


def generate_hook_variants(
    transcript: str,
    out_dir: Path,
    channel_context: str = "",
    model: Optional[str] = None,
    voice_bold: str = HOOK_VOICE_DEFAULT,
    voice_question: str = HOOK_VOICE_FEMALE,
    voice_story: str = HOOK_VOICE_DEFAULT,
) -> list[HookVariant]:
    """Generate 3 hook variants (bold, question, story) with TTS audio.

    Returns list of 3 HookVariant objects, one for each style.
    Falls back to heuristic hooks if AI generation fails.

    Args:
        transcript: Source text for hook generation
        out_dir: Directory to save hook.txt and MP3 files
        channel_context: Channel name for context
        model: OpenAI model to use
        voice_*: Voice for each variant

    Returns:
        List of 3 HookVariant objects
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    # Try AI generation
    ai_hooks = _generate_hook_variants_ai(transcript, channel_context, model)
    has_api_key = bool(os.getenv("OPENAI_API_KEY"))

    # Fallback to heuristic
    heuristic = _heuristic_hook(transcript)
    variants_text = [
        ai_hooks[0] or heuristic,  # bold
        ai_hooks[1] or heuristic,  # question
        ai_hooks[2] or heuristic,  # story
    ]

    # Generate audio for each variant
    styles = ["bold", "question", "story"]
    voices = [voice_bold, voice_question, voice_story]
    variants = []

    for style, hook_text, voice in zip(styles, variants_text, voices):
        variant_dir = out_dir / f"variant-{style}"
        variant_dir.mkdir(parents=True, exist_ok=True)

        # Save text
        (variant_dir / "hook.txt").write_text(hook_text, encoding="utf-8")

        # Generate audio
        mp3_path = variant_dir / "hook.mp3"
        audio_generated = False
        duration = 0.0

        try:
            synthesize_hook_audio(hook_text, mp3_path, voice=voice)
            duration = _probe_audio_duration(mp3_path)
            audio_generated = True
        except Exception as exc:
            print(f"[hook-variants] TTS falhou para {style}: {exc}", flush=True)
            mp3_path = None
            duration = 0.0

        used_ai = has_api_key and ai_hooks[styles.index(style)] is not None

        # Log hook generation
        log_event("hook_generated", {
            "style": style,
            "duration_s": duration,
            "success": audio_generated,
            "fallback_to_heuristic": not used_ai,
            "used_ai": used_ai,
            "channel": channel_context or "Unknown"
        })

        variants.append(
            HookVariant(
                text=hook_text,
                style=style,
                audio_path=mp3_path if audio_generated else None,
                duration_s=duration,
                used_ai=used_ai,
            )
        )

    return variants


if __name__ == "__main__":
    from datetime import datetime

    # Example usage
    test_transcript = """
    O mercado de cripto caiu 40% em uma semana. Mas isso pode ser
    oportunidade para investidores que entendem o jogo. Vários bilionários
    estao comprando agora, preparando para a proxima alta.
    """

    out_dir = Path(f"test-variants-{datetime.now().strftime('%Y%m%d%H%M%S')}")
    variants = generate_hook_variants(test_transcript, out_dir, "Poder em Jogo")

    for v in variants:
        print(f"\n[{v.style.upper()}] ({v.duration_s:.2f}s)")
        print(f"  {v.text}")
        print(f"  Audio: {v.audio_path}")
        print(f"  AI: {v.used_ai}")
