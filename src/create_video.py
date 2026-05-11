from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import time
import textwrap
import wave
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import edge_tts
import imageio_ffmpeg
import requests
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from hw_encoder import video_encoder_args


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
WORK = ROOT / ".work"
WIDTH, HEIGHT = 2160, 3840
USER_AGENT = "poder-em-jogo-automation/1.0 (local creator workflow)"
TRANSITION_SECONDS = 0.45
VIDEO_CRF = "23"
VIDEO_MAXRATE = "18000k"
VIDEO_BUFSIZE = "36000k"


def sc(value: int | float) -> int:
    return int(value * WIDTH / 1080)


@dataclass
class Segment:
    title: str
    narration: str


@dataclass
class MicroScene:
    title: str
    caption: str
    narration: str
    image_index: int


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")[:70] or "video"


def ffmpeg_path() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def run_ffmpeg(args: list[str]) -> None:
    subprocess.run([ffmpeg_path(), "-y", *args], check=True)


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    size = sc(size)
    candidates = [
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def fallback_script(topic: str) -> dict:
    clean_topic = topic.strip().rstrip("?")
    return {
        "topic": clean_topic,
        "title": f"{clean_topic}: o movimento por tras do tabuleiro",
        "hook": f"O erro e pensar que {clean_topic} e so uma noticia. Na verdade, esse tema mostra quem esta ganhando poder no tabuleiro mundial.",
        "segments": [
            {
                "title": "O movimento visivel",
                "narration": f"Quando falamos de {clean_topic}, o erro e olhar apenas para a manchete. O primeiro movimento e entender quem ganha tempo, influencia e poder de negociacao.",
            },
            {
                "title": "O interesse real",
                "narration": "Na geopolitica, quase nada acontece por acaso. Estados buscam seguranca, acesso a recursos, rotas comerciais, tecnologia e capacidade de pressionar adversarios.",
            },
            {
                "title": "Quem esta reagindo",
                "narration": "O segundo ponto e observar as reacoes. Aliados, rivais e mercados costumam revelar se um movimento e pequeno ou se muda o equilibrio regional.",
            },
            {
                "title": "O efeito domino",
                "narration": "Uma decisao local pode afetar energia, moedas, acordos militares, cadeias de suprimento e ate eleicoes em outros paises.",
            },
            {
                "title": "A pergunta-chave",
                "narration": "A pergunta nao e apenas o que aconteceu. A pergunta e: quem fica com mais poder depois desse movimento?",
            },
        ],
        "caption": f"{clean_topic} explicado em linguagem simples. Qual movimento voce acha que vem agora?",
        "hashtags": ["#poderemjogo", "#poder", "#negocios", "#ia", "#economia"],
        "engagement_question": "Quem voce acha que ganha mais poder com esse movimento?",
        "image_queries": fallback_image_queries(clean_topic),
    }


def fallback_image_queries(topic: str) -> list[str]:
    lower = topic.lower()
    if "taiwan" in lower:
        return [
            "Taipei skyline Taiwan",
            "Taiwan Strait map",
            "semiconductor wafer factory",
            "United States Navy aircraft carrier Pacific",
            "container ship port Taiwan",
            "Taiwan flag Taipei",
        ]
    if "china" in lower and "ouro" in lower:
        return [
            "gold bars vault",
            "People's Bank of China building",
            "Shanghai skyline financial district",
            "central bank gold reserves",
            "US dollar banknotes gold bars",
            "global trade map Asia",
        ]
    if "ormuz" in lower or "petr" in lower or "oleo" in lower:
        return [
            "oil tanker sea",
            "Strait of Hormuz map",
            "Persian Gulf oil terminal",
            "crude oil barrels",
            "container ship shipping lane",
            "world energy map",
        ]
    return [
        "world political map",
        "United Nations General Assembly",
        "container ship global trade",
        "military aircraft diplomacy",
        "financial district skyline",
        "satellite view earth night",
    ]


def fallback_hook_title(topic: str) -> str:
    lower = topic.lower()
    if "taiwan" in lower:
        return "TAIWAN NAO E SO UMA ILHA"
    if "china" in lower and "ouro" in lower:
        return "A CHINA ESTA SE PROTEGENDO?"
    if "ormuz" in lower:
        return "ESSE ESTREITO PODE MEXER COM O MUNDO"
    if "petr" in lower or "oleo" in lower:
        return "PETROLEO TAMBEM E PODER"
    return "O MOVIMENTO ESCONDIDO"


def hook_screen_text(topic: str) -> str:
    lower = topic.lower()
    if "china" in lower and "ouro" in lower:
        return "ISSO NAO E SO UMA COMPRA DE OURO."
    if "taiwan" in lower:
        return "ESSA ILHA MEXE COM O EQUILIBRIO DO PACIFICO."
    if "ormuz" in lower:
        return "ESSE PONTO NO MAPA PODE MEXER COM O PRECO DO PETROLEO."
    if "petr" in lower or "oleo" in lower:
        return "QUEM CONTROLA ENERGIA CONTROLA PRESSAO."
    return "ISSO NAO E APENAS UMA NOTICIA."


def generate_with_openai(topic: str) -> dict | None:
    if not os.getenv("OPENAI_API_KEY"):
        return None
    try:
        from openai import OpenAI

        client = OpenAI()
        prompt = f"""
Crie um roteiro original em portugues do Brasil para TikTok do canal @poderemjogo.
Tema: {topic}
Regras:
- 60 a 90 segundos.
- Linguagem clara, analitica e viciante.
- Comece com um gancho forte.
- Nao invente fatos recentes especificos se nao tiver certeza.
- Foque em explicacao geopolitica evergreen.
- Retorne JSON valido com: topic, title, hook, segments (5 itens com title e narration), caption, hashtags, engagement_question, image_queries.
- image_queries deve ter 6 buscas em ingles para imagens realistas de apoio, sem marcas e sem pessoas especificas quando nao necessario.
"""
        response = client.responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            input=prompt,
        )
        text = response.output_text.strip()
        return json.loads(text)
    except Exception as exc:
        print(f"[aviso] Falha ao usar OpenAI; usando roteiro local. Motivo: {exc}")
        return None


def build_script(topic: str) -> dict:
    load_dotenv(ROOT / ".env")
    script = generate_with_openai(topic) or fallback_script(topic)
    script.setdefault("engagement_question", "Qual lado voce acha que ganha mais com isso?")
    script.setdefault("image_queries", fallback_script(topic)["image_queries"])
    return script


async def synthesize_voice(text: str, voice: str, mp3_path: Path, rate: str, pitch: str) -> None:
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await communicate.save(str(mp3_path))


def audio_duration_seconds(mp3_path: Path, wav_path: Path) -> float:
    run_ffmpeg(["-i", str(mp3_path), "-ac", "1", "-ar", "44100", str(wav_path)])
    with wave.open(str(wav_path), "rb") as wav:
        return wav.getnframes() / float(wav.getframerate())


def wrapped_lines(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def cover_image(image: Image.Image) -> Image.Image:
    image = image.convert("RGB")
    src_w, src_h = image.size
    scale = max(WIDTH / src_w, HEIGHT / src_h)
    resized = image.resize((int(src_w * scale), int(src_h * scale)), Image.Resampling.LANCZOS)
    left = (resized.width - WIDTH) // 2
    top = (resized.height - HEIGHT) // 2
    return resized.crop((left, top, left + WIDTH, top + HEIGHT))


def make_fallback_background(index: int) -> Image.Image:
    palettes = [
        ("#101827", "#273b56", "#d8b95f"),
        ("#111827", "#3b2946", "#e3b14a"),
        ("#08111f", "#234b58", "#d8b95f"),
        ("#17120f", "#443429", "#cfa85a"),
    ]
    top, bottom, accent = palettes[index % len(palettes)]
    img = Image.new("RGB", (WIDTH, HEIGHT), top)
    draw = ImageDraw.Draw(img)
    for y in range(HEIGHT):
        ratio = y / HEIGHT
        t = tuple(int(top[i:i+2], 16) for i in (1, 3, 5))
        b = tuple(int(bottom[i:i+2], 16) for i in (1, 3, 5))
        color = tuple(int(t[c] * (1 - ratio) + b[c] * ratio) for c in range(3))
        draw.line([(0, y), (WIDTH, y)], fill=color)
    draw.line((sc(110), sc(290), sc(970), sc(1620)), fill=accent, width=sc(4))
    draw.line((sc(160), sc(1520), sc(880), sc(420)), fill=accent, width=sc(2))
    return img


def search_commons_image(query: str) -> tuple[Image.Image | None, str | None]:
    api = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": "6",
        "gsrlimit": "8",
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "iiurlwidth": "1600",
        "format": "json",
    }
    try:
        response = requests.get(api, params=params, headers={"User-Agent": USER_AGENT}, timeout=15)
        response.raise_for_status()
        pages = response.json().get("query", {}).get("pages", {}).values()
        for page in pages:
            title = page.get("title", "").lower()
            if title.endswith((".pdf", ".djvu", ".svg", ".tif", ".tiff")):
                continue
            info = page.get("imageinfo", [{}])[0]
            url = info.get("thumburl") or info.get("url")
            if not url or not url.lower().split("?")[0].endswith((".jpg", ".jpeg", ".png", ".webp")):
                continue
            time.sleep(0.7)
            image_response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
            image_response.raise_for_status()
            tmp = WORK / f"commons-{slugify(query)}.img"
            tmp.write_bytes(image_response.content)
            image = Image.open(tmp)
            attribution = page.get("title", "Wikimedia Commons")
            return cover_image(image), attribution
    except Exception as exc:
        print(f"[aviso] Nao consegui baixar imagem para '{query}': {exc}")
    return None, None


def get_backgrounds(script: dict, count: int, out_dir: Path) -> list[Image.Image]:
    queries = list(script.get("image_queries") or [])
    topic = script.get("topic", "")
    for query in fallback_image_queries(topic):
        if len(queries) >= count:
            break
        if query not in queries:
            queries.append(query)
    while len(queries) < count:
        queries.append("world political map")

    attributions: list[str] = []
    backgrounds: list[Image.Image] = []
    for index in range(count):
        image, attribution = search_commons_image(queries[index])
        if image is None:
            image = make_fallback_background(index)
        else:
            attributions.append(f"{index + 1}. {attribution} - Wikimedia Commons query: {queries[index]}")
        backgrounds.append(image)

    if attributions:
        (out_dir / "creditos-imagens.txt").write_text("\n".join(attributions) + "\n", encoding="utf-8")
    return backgrounds


def draw_centered_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, y: int, fill: str, max_width: int, line_gap: int = 12) -> int:
    lines = wrapped_lines(draw, text, font, max_width)
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (WIDTH - (bbox[2] - bbox[0])) // 2
        draw.text((x, y), line, font=font, fill=fill)
        y += (bbox[3] - bbox[1]) + line_gap
    return y


def draw_text_with_shadow(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: str,
    shadow: str = "#05070d",
    offset: int | None = None,
) -> None:
    ox = offset if offset is not None else sc(4)
    x, y = xy
    draw.text((x + ox, y + ox), text, font=font, fill=shadow)
    draw.text((x, y), text, font=font, fill=fill)


def overlay_caption(text: str, limit: int = 74) -> str:
    first_sentence = re.split(r"(?<=[.!?])\s+", text.strip())[0]
    caption = first_sentence if first_sentence else text.strip()
    if len(caption) <= limit:
        return caption
    return caption[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "..."


def split_into_sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part.strip()]


def split_caption_chunks(text: str, max_chars: int = 44) -> list[str]:
    words = re.sub(r"\s+", " ", text.strip()).split()
    chunks: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = word
    if current:
        chunks.append(current)
    return chunks


def build_micro_scenes(script: dict, segments: list[Segment]) -> list[MicroScene]:
    scenes: list[MicroScene] = []
    for index, segment in enumerate(segments):
        sentences = split_into_sentences(segment.narration) or [segment.narration]
        for sentence in sentences:
            for chunk in split_caption_chunks(sentence, 46):
                scenes.append(
                    MicroScene(
                        title=segment.title if not scenes else "",
                        caption=chunk.upper(),
                        narration=chunk,
                        image_index=index,
                    )
                )
    if scenes:
        scenes[0].title = fallback_hook_title(script["topic"])
        scenes[0].caption = hook_screen_text(script["topic"])
    return scenes


def make_slide(
    path: Path,
    title: str,
    body: str,
    index: int,
    total: int,
    background: Image.Image,
    question: str,
    topic: str,
    compact: bool = False,
) -> None:
    img = background.copy().convert("RGB")
    img = ImageEnhance.Color(img).enhance(0.92)
    img = ImageEnhance.Contrast(img).enhance(1.12)
    img = ImageEnhance.Sharpness(img).enhance(1.08)
    draw = ImageDraw.Draw(img)
    title_font = load_font(56, bold=True)
    body_font = load_font(52 if compact else 42, bold=True)
    label_font = load_font(26, bold=True)
    small_font = load_font(22)
    cta_font = load_font(34, bold=True)

    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    for y in range(HEIGHT):
        alpha = int(50 + (y / HEIGHT) * 125)
        odraw.line([(0, y), (WIDTH, y)], fill=(0, 0, 0, alpha))
    odraw.rectangle((0, 0, WIDTH, sc(250)), fill=(3, 6, 14, 115))
    odraw.rectangle((0, sc(1390), WIDTH, HEIGHT), fill=(3, 6, 14, 130))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    draw.rectangle((sc(76), sc(74), sc(1004), sc(80)), fill="#d8b95f")
    draw_text_with_shadow(draw, (sc(76), sc(118)), "@poderemjogo", label_font, "#d8b95f", offset=sc(2))
    draw.text((sc(925), sc(118)), f"{index}/{total}", font=small_font, fill="#d7e0f2")

    if title:
        title_lines = wrapped_lines(draw, title.upper(), title_font, sc(870))
        y = sc(300)
        for line in title_lines[:2]:
            bbox = draw.textbbox((0, 0), line, font=title_font)
            x = (WIDTH - (bbox[2] - bbox[0])) // 2
            draw_text_with_shadow(draw, (x, y), line, title_font, "#ffffff", offset=sc(5))
            y += bbox[3] - bbox[1] + sc(18)

    summary = body.upper() if compact else (hook_screen_text(topic) if index == 1 else overlay_caption(" ".join(textwrap.wrap(body, width=84))))
    lower_top = sc(1210 if compact else 1280)
    caption_lines = wrapped_lines(draw, summary.upper(), body_font, sc(830))
    caption_height = len(caption_lines) * sc(58) + sc(80)
    draw.rounded_rectangle(
        (sc(92), lower_top, sc(988), lower_top + caption_height),
        radius=sc(18),
        fill=(5, 8, 16),
        outline="#2c3444",
        width=sc(1),
    )
    cy = lower_top + sc(38)
    for line in caption_lines[:2 if compact else 3]:
        bbox = draw.textbbox((0, 0), line, font=body_font)
        x = (WIDTH - (bbox[2] - bbox[0])) // 2
        draw.text((x, cy), line, font=body_font, fill="#f8fafc")
        cy += bbox[3] - bbox[1] + sc(16)

    if compact and index != total:
        pass
    elif index == total:
        draw.rounded_rectangle((sc(88), sc(1660), sc(992), sc(1764)), radius=sc(20), fill="#d8b95f")
        draw_centered_text(draw, f"COMENTE: {question}".upper(), cta_font, sc(1684), "#101827", sc(830), sc(8))
    elif index == 1:
        draw.rounded_rectangle((sc(108), sc(1660), sc(972), sc(1764)), radius=sc(20), fill="#d8b95f")
        draw_centered_text(draw, "A PERGUNTA FINAL MUDA TUDO", cta_font, sc(1684), "#101827", sc(780), sc(8))
    else:
        draw.line((sc(156), sc(1720), sc(924), sc(1720)), fill="#d8b95f", width=sc(2))
        draw_centered_text(draw, "siga para entender o tabuleiro mundial", load_font(28, bold=True), sc(1746), "#f8fafc", sc(760), sc(8))

    img.save(path, quality=95)


def make_motion_clip(image_path: Path, clip_path: Path, duration: float, direction: int) -> None:
    frames = max(1, int(duration * 30))
    zoom = "min(zoom+0.0026,1.12)" if duration <= 3.2 else "min(zoom+0.0010,1.08)"
    x_expr = "iw/2-(iw/zoom/2)"
    y_expr = "ih/2-(ih/zoom/2)"
    if direction % 3 == 1:
        x_expr = "(iw-iw/zoom)*on/{frames}".format(frames=frames)
    elif direction % 3 == 2:
        x_expr = "(iw-iw/zoom)*(1-on/{frames})".format(frames=frames)
    run_ffmpeg([
        "-loop", "1",
        "-i", str(image_path),
        "-t", f"{duration:.2f}",
        "-vf",
        (
            f"scale={sc(1200)}:-2,"
            f"zoompan=z='{zoom}':x='{x_expr}':y='{y_expr}':d={frames}:s={WIDTH}x{HEIGHT}:fps=30,"
            "eq=contrast=1.08:saturation=1.10:brightness=-0.025,"
            "unsharp=5:5:0.55:3:3:0.20,"
            "vignette=PI/5,"
            "noise=alls=2:allf=t+u,"
            "format=yuv420p,setsar=1"
        ),
        "-an",
        *video_encoder_args(VIDEO_CRF, VIDEO_MAXRATE, VIDEO_BUFSIZE),
        str(clip_path),
    ])


def create_visual_timeline(clips: list[Path], raw_video: Path, clip_duration: float) -> None:
    if len(clips) == 1:
        run_ffmpeg(["-i", str(clips[0]), "-c", "copy", str(raw_video)])
        return

    inputs: list[str] = []
    for clip in clips:
        inputs.extend(["-i", str(clip)])

    chains: list[str] = []
    previous = "0:v"
    for i in range(1, len(clips)):
        output = f"v{i}"
        offset = max(0.1, i * (clip_duration - TRANSITION_SECONDS))
        chains.append(
            f"[{previous}][{i}:v]xfade=transition=fade:duration={TRANSITION_SECONDS}:offset={offset:.3f}[{output}]"
        )
        previous = output

    run_ffmpeg([
        *inputs,
        "-filter_complex", ";".join(chains),
        "-map", f"[{previous}]",
        *video_encoder_args(VIDEO_CRF, VIDEO_MAXRATE, VIDEO_BUFSIZE),
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(raw_video),
    ])


def create_fast_timeline(clips: list[Path], raw_video: Path) -> None:
    list_file = raw_video.with_suffix(".txt")
    list_file.write_text("".join(f"file '{clip.as_posix()}'\n" for clip in clips), encoding="utf-8")
    run_ffmpeg([
        "-f", "concat",
        "-safe", "0",
        "-i", str(list_file),
        *video_encoder_args(VIDEO_CRF, VIDEO_MAXRATE, VIDEO_BUFSIZE),
        "-pix_fmt", "yuv420p",
        "-r", "30",
        "-movflags", "+faststart",
        str(raw_video),
    ])


def create_video(script: dict, voice: str, voice_rate: str = "-4%", voice_pitch: str = "+0Hz") -> Path:
    OUTPUTS.mkdir(exist_ok=True)
    WORK.mkdir(exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = slugify(script["topic"])
    out_dir = OUTPUTS / f"{stamp}-{slug}"
    out_dir.mkdir(parents=True, exist_ok=True)

    segments = [Segment(fallback_hook_title(script["topic"]), script["hook"])] + [
        Segment(item["title"], item["narration"]) for item in script["segments"]
    ]
    narration = "\n\n".join(seg.narration for seg in segments)

    script_path = out_dir / "roteiro.json"
    script_path.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "descricao.txt").write_text(
        script["caption"] + "\n\n" + " ".join(script["hashtags"]) + "\n",
        encoding="utf-8",
    )

    mp3_path = out_dir / "narracao.mp3"
    wav_path = out_dir / "narracao.wav"
    asyncio.run(synthesize_voice(narration, voice, mp3_path, voice_rate, voice_pitch))
    duration = audio_duration_seconds(mp3_path, wav_path)

    micro_scenes = build_micro_scenes(script, segments)
    target_scene_count = min(max(len(micro_scenes), 18), 34)
    micro_scenes = micro_scenes[:target_scene_count]
    if micro_scenes and micro_scenes[-1].caption != script["engagement_question"].upper():
        micro_scenes.append(
            MicroScene(
                title="",
                caption=f"COMENTE: {script['engagement_question']}".upper(),
                narration=script["engagement_question"],
                image_index=len(segments) - 1,
            )
        )
    scene_duration = max(1.65, min(2.9, duration / max(len(micro_scenes), 1)))
    backgrounds = get_backgrounds(script, len(segments), out_dir)
    clips: list[Path] = []
    for i, scene in enumerate(micro_scenes, start=1):
        slide_path = out_dir / f"slide-{i:02d}.jpg"
        clip_path = out_dir / f"clip-{i:02d}.mp4"
        background = backgrounds[min(scene.image_index, len(backgrounds) - 1)]
        make_slide(
            slide_path,
            scene.title,
            scene.caption,
            i,
            len(micro_scenes),
            background,
            script["engagement_question"],
            script["topic"],
            compact=True,
        )
        make_motion_clip(slide_path, clip_path, scene_duration, i)
        clips.append(clip_path)

    raw_video = out_dir / "video-sem-audio.mp4"
    final_video = out_dir / "video-final.mp4"
    create_fast_timeline(clips, raw_video)
    run_ffmpeg([
        "-i", str(raw_video),
        "-i", str(mp3_path),
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "160k",
        "-af", "loudnorm=I=-16:LRA=10:TP=-1.5,acompressor=threshold=-18dB:ratio=2.2:attack=8:release=80",
        "-shortest",
        "-movflags", "+faststart",
        str(final_video),
    ])

    checklist = """Checklist antes de publicar:
- Assista ao video inteiro.
- Confirme se o tema nao depende de noticia recente sem verificacao.
- Use capa com o titulo mais forte.
- Poste com a descricao.txt.
- Depois de 24h, registre views, retencao, comentarios, salvamentos e seguidores ganhos.
"""
    (out_dir / "checklist.txt").write_text(checklist, encoding="utf-8")
    return final_video


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", required=True)
    parser.add_argument("--voice", default="pt-BR-ThalitaMultilingualNeural")
    parser.add_argument("--voice-rate", default="-4%")
    parser.add_argument("--voice-pitch", default="+0Hz")
    args = parser.parse_args()

    script = build_script(args.topic)
    final_video = create_video(script, args.voice, args.voice_rate, args.voice_pitch)
    print(f"Video criado: {final_video}")


if __name__ == "__main__":
    main()
