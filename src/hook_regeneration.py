"""Hook regeneration: GPT writes a sharper opening, Edge-TTS narrates it.

Replaces the first 3-5 seconds of a clip with an AI-rewritten hook designed
for maximum stopping power on TikTok. Falls back to heuristic hook if no
OpenAI key is available.

Pipeline:
    transcript (first 30-60s) → GPT hook (8-15 words PT-BR) → Edge-TTS MP3
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


HOOK_VOICE_DEFAULT = "pt-BR-AntonioNeural"   # masc. — confident, news-anchor feel
HOOK_VOICE_FEMALE = "pt-BR-FranciscaNeural"  # fem. — energetic
HOOK_RATE = "+8%"      # slightly faster than default for energy
HOOK_PITCH = "+2Hz"

SYSTEM_PROMPT = (
    "Voce e um editor de TikTok especializado em ganchos virais para conteudo "
    "de geopolitica, poder e negocios em PT-BR. Sua tarefa: reescrever o inicio "
    "de um trecho para que prenda a atencao nos primeiros 3 segundos.\n\n"
    "Regras OBRIGATORIAS:\n"
    "- 8 a 15 palavras, NUNCA mais\n"
    "- Sem clickbait barato, mas com tensao real\n"
    "- Termina com uma promessa, pergunta ou afirmacao forte\n"
    "- Sem emojis, sem hashtags\n"
    "- Use linguagem falada, direta, em portugues do Brasil\n"
    "- NAO comece com 'Voce sabia que', 'Imagine', 'Olha so' ou cliches\n"
    "- Pode comecar com numero, nome proprio, contradição ou pergunta direta\n\n"
    "Retorne APENAS JSON: {\"hook\": \"frase final aqui\"}"
)


@dataclass
class HookResult:
    text: str
    audio_path: Optional[Path]
    used_ai: bool
    duration_s: float


def _has_api_key() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))


def _heuristic_hook(transcript: str) -> str:
    """Fallback when no AI: use the first strong-looking sentence."""
    text = re.sub(r"\s+", " ", transcript).strip()
    sentences = re.split(r"(?<=[.!?])\s+", text)
    for s in sentences:
        words = s.split()
        if 6 <= len(words) <= 16:
            return s.rstrip(".!?")
    # Fallback: first 12 words
    words = text.split()[:12]
    return " ".join(words).rstrip(",.;:")


def _generate_hook_text_ai(
    transcript: str,
    channel_context: str = "",
    model: Optional[str] = None,
) -> Optional[str]:
    """Ask GPT for a punchy hook. Returns None on any failure."""
    try:
        from openai import OpenAI
    except ImportError:
        return None

    model = model or os.getenv("OPENAI_MODEL") or "gpt-4.1-mini"
    user_prompt = (
        f"Canal: {channel_context or 'Poder em Jogo (geopolitica, poder, negocios)'}\n\n"
        f"Trecho original (primeiros segundos):\n{transcript[:1500]}\n\n"
        "Reescreva o inicio (8-15 palavras) para prender atencao."
    )
    try:
        client = OpenAI()
        response = client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            temperature=0.7,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = response.choices[0].message.content or "{}"
        data = json.loads(content)
        hook = (data.get("hook") or "").strip()
        if 4 <= len(hook.split()) <= 22:
            return hook
        return None
    except Exception as exc:
        print(f"[hook-regen] GPT falhou: {exc}", flush=True)
        return None


async def _synthesize_async(text: str, voice: str, mp3_path: Path) -> None:
    import edge_tts
    communicate = edge_tts.Communicate(text, voice, rate=HOOK_RATE, pitch=HOOK_PITCH)
    await communicate.save(str(mp3_path))


def synthesize_hook_audio(
    text: str,
    output_path: Path,
    voice: str = HOOK_VOICE_DEFAULT,
) -> Path:
    """Generate MP3 narration. Raises on failure."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(_synthesize_async(text, voice, output_path))
    return output_path


def _probe_audio_duration(mp3_path: Path) -> float:
    """Return MP3 duration in seconds via ffprobe-like ffmpeg call."""
    import subprocess
    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(mp3_path)],
        capture_output=True, text=True, encoding="utf-8", errors="ignore",
    )
    text = (result.stderr or "")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if m:
        h, mi, s = m.groups()
        return int(h) * 3600 + int(mi) * 60 + float(s)
    return 0.0


def generate_hook(
    transcript: str,
    out_dir: Path,
    channel_context: str = "",
    voice: str = HOOK_VOICE_DEFAULT,
    model: Optional[str] = None,
    require_ai: bool = False,
) -> HookResult:
    """Generate hook text + audio. Saves hook.txt and hook.mp3 in out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)

    used_ai = False
    hook_text: Optional[str] = None
    if _has_api_key():
        hook_text = _generate_hook_text_ai(transcript, channel_context, model)
        used_ai = hook_text is not None

    if not hook_text:
        if require_ai:
            raise RuntimeError("require_ai=True but GPT hook generation failed.")
        hook_text = _heuristic_hook(transcript)

    (out_dir / "hook.txt").write_text(hook_text, encoding="utf-8")

    mp3_path = out_dir / "hook.mp3"
    try:
        synthesize_hook_audio(hook_text, mp3_path, voice=voice)
    except Exception as exc:
        print(f"[hook-regen] Edge-TTS falhou: {exc}", flush=True)
        return HookResult(text=hook_text, audio_path=None, used_ai=used_ai, duration_s=0.0)

    duration = _probe_audio_duration(mp3_path)
    return HookResult(text=hook_text, audio_path=mp3_path, used_ai=used_ai, duration_s=duration)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Generate AI hook + TTS audio.")
    parser.add_argument("--transcript", required=True, help="Transcript text or path to .txt.")
    parser.add_argument("--output-dir", required=True, help="Directory to save hook.txt and hook.mp3.")
    parser.add_argument("--voice", default=HOOK_VOICE_DEFAULT)
    parser.add_argument("--context", default="", help="Channel context.")
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    text = Path(args.transcript).read_text(encoding="utf-8") if Path(args.transcript).exists() else args.transcript
    result = generate_hook(
        text, Path(args.output_dir),
        channel_context=args.context, voice=args.voice, model=args.model,
    )
    print(f"Hook ({'AI' if result.used_ai else 'heuristic'}): {result.text}")
    print(f"Audio: {result.audio_path} ({result.duration_s:.2f}s)")


if __name__ == "__main__":
    main()
