from __future__ import annotations

import argparse
import html
import json
import math
import re
import subprocess
import sys
import unicodedata
import wave
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import imageio_ffmpeg

from youtube_to_cut import download_youtube


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".work" / "analysis"
OUTPUTS = ROOT / "outputs"


def write_user_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8-sig")


@dataclass
class CaptionLine:
    start: float
    end: float
    text: str


@dataclass
class Candidate:
    score: int
    start: float
    end: float
    headline: str
    reason: str
    text: str
    text_score: int = 0
    hook_score: int = 0
    hook_reason: str = ""
    start_adjustment: float = 0.0
    media_score: int = 0
    editorial_score: int = 0
    editorial_reason: str = ""
    channel_score: int = 0
    channel_reason: str = ""
    media_metrics: dict[str, float] | None = None


@dataclass
class MediaSignals:
    audio_energy: list[float]
    scene_times: list[float]


def classify_score(score: int) -> str:
    if score >= 85:
        return "Muito alto"
    if score >= 70:
        return "Alto"
    if score >= 55:
        return "Medio"
    if score >= 40:
        return "Baixo"
    return "Ruim"


HOOK_WORDS = [
    "ninguém",
    "ninguem",
    "segredo",
    "verdade",
    "erro",
    "problema",
    "crise",
    "guerra",
    "poder",
    "dinheiro",
    "bilhões",
    "bilhoes",
    "trilhões",
    "trilhoes",
    "china",
    "eua",
    "russia",
    "rússia",
    "taiwan",
    "otan",
    "petróleo",
    "petroleo",
    "dólar",
    "dolar",
    "ouro",
    "energia",
    "chip",
    "semicondutor",
    "mapa",
]

TENSION_WORDS = [
    "mas",
    "porém",
    "porem",
    "só que",
    "so que",
    "na verdade",
    "o ponto",
    "o problema",
    "o detalhe",
    "por isso",
    "então",
    "entao",
    "se",
    "porque",
]

OPENING_WORDS = [
    "olha",
    "imagina",
    "presta atencao",
    "presta atenção",
    "o problema",
    "o ponto",
    "o detalhe",
    "a verdade",
    "na verdade",
    "ninguem",
    "ninguém",
    "voce",
    "você",
    "sabe",
    "por que",
    "porque",
    "isso",
    "essa",
    "esse",
]

BAD_OPENING_STARTS = [
    "e ",
    "é ",
    "eh ",
    "aí ",
    "ai ",
    "né ",
    "então ",
    "entao ",
    "cara ",
    "tipo ",
    "deles ",
    "dele ",
    "dela ",
    "eles ",
    "elas ",
    "isso ",
    "aquilo ",
    "que ",
    "porque ",
    "prolabore",
    "pró-labore",
    "fechou",
    "incrível",
    "incrivel",
    "sim ",
    "mas ",
    "tá ",
    "ta ",
    "falou",
    "falei",
    "com ",
    "sozinho",
    "em ",
    "olha ",
    "acho ",
    "vlogzinho",
    "para subsidiar",
    "pra subsidiar",
    "parada",
]

BAD_OPENING_PHRASES = [
    "mas o nome",
    "mostra tá certo",
    "mostra ta certo",
    "prazer estar aqui",
    "obrigado pelo convite",
    "nessa linha",
    "nessa evolucao",
    "nessa evolução",
    "qual que é",
    "qual que e",
    "quer dizer que",
    "vez mais",
    "média e",
    "media e",
    "perna longa",
    "mais para frente",
    "mais pra frente",
    "toda vez que eu vejo",
    "eu tava falando",
    "essas referências",
    "essas referencias",
    "dimensão eu tenho",
    "dimensao eu tenho",
    "sabe valter",
    "sabe walter",
    "né exato",
    "ne exato",
    "exato enquanto",
    "concorrência a lado",
    "concorrencia a lado",
    "buscar só que",
    "buscar so que",
    "houve o mobile",
    "prolabore",
    "é verdade",
    "era outra vida",
    "beleza",
    "pois é",
    "pode crer",
    "fechou",
    "incrível, cara",
    "incrivel cara",
    "por falar em negócio",
    "por falar em negocio",
    "vamos falar de negócios",
    "vamos falar de negocios",
    "se inscrever",
    "estamos chegando",
    "canais que",
    "canal de cortes",
    "vai falar mais sobre isso",
    "perguntei se já tava no ar",
    "perguntei se ja tava no ar",
    "falou cara",
    "falei assim",
    "com os caras",
    "tá né",
    "ta ne",
    "vou contar a verdade",
    "faturamento dela",
    "faturamento dele",
    "em companhias normais",
    "eu comecei",
    "eu nasci",
    "2012, quando",
    "2012 quando",
    "olha entao",
    "olha, entao",
    "olha então",
    "olha, então",
    "acho que voces",
    "acho que vocês",
    "vlogzinho",
    "para subsidiar",
    "pra subsidiar",
    "parada, porque",
    "parada porque",
]

FRAGMENT_OPENING_PATTERNS = [
    r"^(nessa|nesse|naquela|naquele|dessa|desse)\b",
    r"^(vez|cada vez|mais|menos)\b",
    r"^(buscar|houve|m[ée]dia|dimens[ãa]o|concorr[êe]ncia|perna|linha)\b",
    r"^(sabe|exato|perfeito)\s+[a-zá-ú]+\b",
    r"\bqual que [ée]\b",
]

STANDALONE_TERMS = [
    "empresa",
    "negocio",
    "negócio",
    "produtividade",
    "inflacao",
    "inflação",
    "inteligencia artificial",
    "inteligência artificial",
    "ia",
    "dinheiro",
    "mercado",
    "poder",
    "tecnologia",
    "china",
    "eua",
    "brasil",
    "governo",
    "guerra",
]

CLOSING_TERMS = [
    "por isso",
    "entao",
    "então",
    "ou seja",
    "no fim",
    "a conclusao",
    "a conclusão",
    "isso significa",
    "o resultado",
    "a consequencia",
    "a consequência",
]

COMMENT_TERMS = [
    "voce",
    "você",
    "sua empresa",
    "seu negocio",
    "seu negócio",
    "quem ganha",
    "quem perde",
    "o que acontece",
    "vale a pena",
    "concorda",
]

THESIS_PATTERNS = [
    (
        "empresa tradicional perde para startup",
        [
            r"\b(startup|startups)\b",
            r"\b(empresa tradicional|negocio tradicional|negócio tradicional|companhias normais)\b",
            r"\b(gestao|gestão|processo|indicador|metrica|métrica|inovacao|inovação|documentacao|documentação)\b",
        ],
    ),
    (
        "gestao vence tamanho",
        [
            r"\b(gestao|gestão|gestao 4 0|gestão 4 0|processo|ritual|reuniao|reunião|indicador|metrica|métrica)\b",
            r"\b(faturamento|empresa grande|empresa pequena|volume de dinheiro|crescimento)\b",
        ],
    ),
    (
        "mercado esta mudando",
        [
            r"\b(movimento de mercado|digitalizacao|digitalização|mercado|demanda reprimida|tendencia|tendência)\b",
            r"\b(empresas|negocios|negócios|empreendedores|clientes)\b",
        ],
    ),
    (
        "dinheiro revela o jogo",
        [
            r"\b(dinheiro|faturamento|milhoes|milhões|bilhoes|bilhões|receita|vender empresa|vende empresa)\b",
            r"\b(risco|sem risco|prolabore|pró labore|fundador|founder|empresa)\b",
        ],
    ),
    (
        "ia muda empresas",
        [
            r"\b(ia|inteligencia artificial|inteligência artificial|automacao|automação)\b",
            r"\b(empresa|negocio|negócio|mercado|trabalho|produtividade)\b",
        ],
    ),
    (
        "geopolitica e poder",
        [
            r"\b(china|eua|estados unidos|russia|rússia|otan|guerra|energia|dolar|dólar|petroleo|petróleo)\b",
            r"\b(poder|mercado|estado|governo|economia|mundo)\b",
        ],
    ),
]

WEAK_CHATTER_TERMS = [
    "presente",
    "medalha",
    "idade",
    "mais velho",
    "mais idoso",
    "conheci ele",
    "conheci o",
    "veio aqui",
    "já veio aqui",
    "ja veio aqui",
    "meu amigo",
    "pô cara",
    "nossa",
    "caramba",
    "legal",
    "baita",
    "tênis",
    "tenis",
    "paraquedas",
    "para queda",
    "fratura",
    "amputar",
    "podcast",
    "convidado",
    "contar a história",
    "contar a historia",
]

COMMERCIAL_TERMS = [
    "airbnb",
    "patrocin",
    "publicidade",
    "propaganda",
    "oferecimento",
    "cupom",
    "desconto",
    "promocao",
    "promoção",
    "link na descricao",
    "link na descrição",
    "acesse o link",
    "clique no link",
    "compre agora",
    "assine",
    "assinatura",
    "reservar sua acomodacao",
    "reservar sua acomodação",
    "acomodacao",
    "acomodação",
    "feriado liberado",
    "parceiro",
    "parceria",
    "marca parceira",
    "contabilizei",
    "abrir cnpj",
    "abre seu cnpj",
    "cnpj",
    "nota fiscal",
    "emissao de nota",
    "emissão de nota",
    "impostos",
    "por mes",
    "por mês",
    "por 195",
    "r 195",
    "r$ 195",
    "whatsapp ate",
    "whatsapp até",
    "planos",
    "mensalidade",
    "organizam seus impostos",
    "melhor tipo de empresa",
    "assinantes",
    "vantagens incriveis",
    "vantagens incríveis",
    "ingresso para cinema",
    "servicos e vantagens",
    "serviços e vantagens",
    "antes da gente comecar",
    "antes da gente começar",
    "parabenizar",
    "apoio de",
    "apoia esse",
    "apoia o canal",
    "baixe o app",
    "teste gratis",
    "teste grátis",
    "planos a partir",
    "use o codigo",
    "use o código",
]

COMMERCIAL_OPENING_TERMS = [
    *COMMERCIAL_TERMS,
    "familia e reservar",
    "família e reservar",
    "certo santa",
    "certissimo",
    "certíssimo",
    "vilela",
    "santa?",
]

LOW_VALUE_CONTEXT_TERMS = [
    "meu presente",
    "presente inutil",
    "presente inútil",
    "medalha",
    "iron man",
    "florianopolis",
    "florianópolis",
    "morreu uma garota",
    "problema cardiaco",
    "problema cardíaco",
    "cardiologista",
    "afogar",
    "mais idoso",
    "tem 40 anos",
    "vou fazer 39",
    "conheci o alfredo",
    "erro de portugues",
    "erro de português",
    "e mail marketing",
    "email marketing",
    "ortobom",
    "colchao",
    "colchão",
    "cartao de visita",
    "cartão de visita",
    "imprimia na grafica",
    "imprimia na gráfica",
    "paraquedas",
    "paraquedo",
    "para queda",
    "saltei",
    "saltar sozinho",
    "fratura exposta",
    "placas de titanio",
    "placas de titânio",
    "amputar",
    "amputacao",
    "amputação",
    "fisioterapia",
    "levantar da cama",
    "gelo",
    "presente inutil",
    "presente inútil",
    "jogar tenis",
    "jogar tênis",
    "assinada pelo",
    "veio aqui",
    "me dar presente",
    "vai falar mais sobre isso",
]

WEAK_ENDING_WORDS = {
    "a",
    "o",
    "as",
    "os",
    "um",
    "uma",
    "de",
    "da",
    "do",
    "das",
    "dos",
    "em",
    "no",
    "na",
    "nos",
    "nas",
    "para",
    "pra",
    "por",
    "com",
    "como",
    "que",
    "porque",
    "e",
}


def collapse_repeated_chunks(text: str) -> str:
    words = re.sub(r"\s+", " ", text).strip().split()
    if len(words) < 4:
        return " ".join(words)

    output: list[str] = []
    i = 0
    while i < len(words):
        removed = False
        for size in range(min(10, (len(words) - i) // 2), 1, -1):
            first = [word.lower().strip(".,;:!?") for word in words[i : i + size]]
            second = [word.lower().strip(".,;:!?") for word in words[i + size : i + size * 2]]
            if first == second:
                output.extend(words[i : i + size])
                i += size * 2
                removed = True
                break
        if not removed:
            output.append(words[i])
            i += 1
    return " ".join(output)


def normalize_for_match(text: str) -> str:
    text = html.unescape(text or "").lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace("ã", "a").replace("Ã£".lower(), "a")
    text = re.sub(r"[^a-z0-9% ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_commercial_candidate(text: str, opening_text: str | None = None) -> tuple[bool, str]:
    normalized = normalize_for_match(text)
    opening_source = opening_text if opening_text is not None else " ".join(text.split()[:80])
    opening = normalize_for_match(" ".join(opening_source.split()[:90]))

    opening_terms = [normalize_for_match(term) for term in COMMERCIAL_OPENING_TERMS]
    full_terms = [normalize_for_match(term) for term in COMMERCIAL_TERMS]

    opening_hits = [term for term in opening_terms if term and term in opening]
    if opening_hits:
        return True, "inicio comercial/propaganda: " + ", ".join(opening_hits[:3])

    full_hits = [term for term in full_terms if term and term in normalized]
    if len(full_hits) >= 2:
        return True, "trecho com propaganda: " + ", ".join(full_hits[:3])

    return False, ""


def is_low_value_context(text: str, opening_text: str | None = None) -> tuple[bool, str]:
    normalized = normalize_for_match(text)
    opening_source = opening_text if opening_text is not None else " ".join(text.split()[:80])
    opening = normalize_for_match(" ".join(opening_source.split()[:90]))
    terms = [normalize_for_match(term) for term in LOW_VALUE_CONTEXT_TERMS]
    opening_hits = [term for term in terms if term and term in opening]
    if opening_hits:
        return True, "inicio de bastidor/assunto fraco: " + ", ".join(opening_hits[:3])
    full_hits = [term for term in terms if term and term in normalized]
    if len(full_hits) >= 2:
        return True, "trecho de bastidor/assunto fraco: " + ", ".join(full_hits[:3])
    return False, ""


def thesis_score(text: str, opening_text: str = "") -> tuple[int, str]:
    normalized = normalize_for_match(text)
    opening = normalize_for_match(opening_text or " ".join(text.split()[:70]))
    score = 0
    reasons: list[str] = []

    for label, patterns in THESIS_PATTERNS:
        hits = sum(1 for pattern in patterns if re.search(pattern, normalized))
        opening_hits = sum(1 for pattern in patterns if re.search(pattern, opening))
        if hits >= 2:
            bonus = 14 + min(14, hits * 4) + min(10, opening_hits * 4)
            score += bonus
            reasons.append(label)

    if re.search(r"\b(o ponto|o problema|na verdade|so que|só que|por isso|porque|entao|então)\b", normalized):
        score += 8
        reasons.append("tem raciocinio")
    if re.search(r"\b(nao e|não é|muda|difere|gap|absurdo|muito maior|ficar para tras|ficar para trás)\b", normalized):
        score += 10
        reasons.append("tem contraste forte")
    if "?" in text[:420]:
        score += 6
        reasons.append("abre pergunta")

    return min(45, score), ", ".join(reasons) or "sem tese forte"


def weak_chatter_score(text: str, opening_text: str = "") -> tuple[int, str]:
    normalized = normalize_for_match(text)
    opening = normalize_for_match(opening_text or " ".join(text.split()[:70]))
    hits = [term for term in (normalize_for_match(term) for term in WEAK_CHATTER_TERMS) if term and term in normalized]
    opening_hits = [term for term in (normalize_for_match(term) for term in WEAK_CHATTER_TERMS) if term and term in opening]
    penalty = min(40, len(hits) * 5 + len(opening_hits) * 8)
    if penalty:
        return penalty, "conversa morna/bastidor: " + ", ".join((opening_hits or hits)[:4])
    return 0, ""


def first_sentence(text: str, max_chars: int = 180) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if not clean:
        return ""
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", clean) if part.strip()]
    if not parts:
        parts = [clean]
    sentence = parts[0]
    weak_prefixes = ("ne", "olha entao", "vlogzinho", "acho que", "para subsidiar", "pra subsidiar")
    for part in parts:
        normalized = normalize_for_match(part)
        word_count = len(part.split())
        if word_count <= 4:
            continue
        if normalized.startswith(weak_prefixes) or starts_weak(part):
            continue
        sentence = part
        break
    if len(sentence) > max_chars:
        sentence = sentence[:max_chars].rsplit(" ", 1)[0] + "..."
    return sentence


def title_has_term(normalized_text: str, term: str) -> bool:
    normalized_term = normalize_for_match(term)
    if not normalized_term:
        return False
    if len(normalized_term) <= 3:
        return re.search(rf"\b{re.escape(normalized_term)}\b", normalized_text) is not None
    return normalized_term in normalized_text


def editorial_title(text: str, fallback: str) -> str:
    normalized = normalize_for_match(text)
    title_rules = [
        (["startup", "empresa tradicional", "gestao"], "O ERRO QUE FAZ EMPRESAS GRANDES PERDEREM PARA STARTUPS"),
        (["startup", "negocio tradicional", "processo"], "STARTUPS TEM UMA VANTAGEM QUE EMPRESAS GRANDES IGNORAM"),
        (["startup", "negocio tradicional", "inovacao"], "STARTUPS TEM UMA VANTAGEM QUE EMPRESAS GRANDES IGNORAM"),
        (["startup", "negocio tradicional", "gestao"], "STARTUPS TEM UMA VANTAGEM QUE EMPRESAS GRANDES IGNORAM"),
        (["gestao", "indicador", "metrica"], "GESTAO SEM METRICA VIRA APOSTA"),
        (["processo", "indicador", "metrica"], "GESTAO SEM METRICA VIRA APOSTA"),
        (["movimento de mercado", "digitalizacao"], "A DIGITALIZACAO MUDOU O JOGO DAS EMPRESAS"),
        (["demanda reprimida", "empreendedores"], "EXISTE UMA DEMANDA ESCONDIDA ENTRE EMPREENDEDORES"),
        (["dinheiro", "risco", "empresa"], "O DINHEIRO MOSTRA QUEM ESTA ASSUMINDO O RISCO"),
        (["inteligencia artificial", "empresa"], "A IA VAI PEGAR EMPRESAS DESPREPARADAS"),
        (["chatgpt", "empresa"], "A IA VAI PEGAR EMPRESAS DESPREPARADAS"),
        (["china", "poder"], "A CHINA ESTA MUDANDO O TABULEIRO DO PODER"),
        (["eua", "china"], "EUA E CHINA ESTAO DISPUTANDO MAIS QUE MERCADO"),
    ]
    for terms, title in title_rules:
        if all(title_has_term(normalized, term) for term in terms):
            return title
    return make_headline(fallback or text)


def approval_decision(score: int, hook_score: int, reason: str) -> str:
    reason_lower = reason.lower()
    weak_markers = [
        "inicio quebrado",
        "inicio depende do contexto",
        "primeiras palavras parecem continuacao",
        "conversa morna",
        "bastidor",
        "propaganda",
        "inicio comercial",
        "inicio sem fala suficiente",
    ]
    if any(marker in reason_lower for marker in weak_markers):
        return "REJEITAR"
    if score >= 85 and hook_score >= 70 and "tese forte" in reason_lower:
        return "APROVAR"
    if score >= 75 and hook_score >= 65:
        return "TESTAR"
    return "REJEITAR"


def clean_joined_transcript(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    previous = ""
    for _ in range(4):
        if text == previous:
            break
        previous = text
        text = collapse_repeated_chunks(text)

    words = text.split()
    cleaned: list[str] = []
    for word in words:
        normalized = word.lower().strip(".,;:!?")
        if cleaned and normalized == cleaned[-1].lower().strip(".,;:!?"):
            continue
        cleaned.append(word)
    return " ".join(cleaned)


def trim_weak_ending(text: str, min_words: int = 5) -> str:
    words = text.strip().split()
    while len(words) > min_words and words[-1].lower().strip(".,;:!?") in WEAK_ENDING_WORDS:
        words.pop()
    return " ".join(words).strip(" .,:;")


def run(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=check)


def run_capture(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=False, capture_output=True, text=True, encoding="utf-8", errors="ignore")


def ffmpeg_path() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def seconds_to_timestamp(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return str(timedelta(seconds=seconds)).rjust(8, "0")


def timestamp_to_seconds(value: str) -> float:
    hours, minutes, rest = value.split(":")
    seconds = rest.replace(",", ".")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def clean_caption_text(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\{\\.*?\}", "", text)
    text = text.replace("&nbsp;", " ")
    text = re.sub(r"(?:^|\s)>>+", " ", text)
    text = re.sub(r"\[[^\]]+\]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return collapse_repeated_chunks(text)


def strip_weak_prefix(text: str) -> str:
    text = collapse_repeated_chunks(re.sub(r"\s+", " ", text).strip(" .,:;"))
    patterns = [
        r"^(deles|dele|dela|eles|elas|isso|aquilo),?\s+(porque|que)\s+",
        r"^(e|aí|ai|né|então|entao|cara|tipo),?\s+",
        r"^(porque|que)\s+",
    ]
    changed = True
    while changed:
        changed = False
        for pattern in patterns:
            new_text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip(" .,:;")
            if new_text != text:
                text = new_text
                changed = True
    return text


def starts_weak(text: str) -> bool:
    lower = text.lower().strip()
    if any(phrase in lower[:140] for phrase in BAD_OPENING_PHRASES):
        return True
    if any(re.search(pattern, lower[:80]) for pattern in FRAGMENT_OPENING_PATTERNS):
        return True
    if any(lower.startswith(prefix) for prefix in BAD_OPENING_STARTS):
        return True
    return bool(
        re.match(
            r"^(e|é|eh|aí|ai|né|então|entao|cara|tipo|deles|dele|dela|eles|elas|isso|aquilo|que|porque)[,;:\s]",
            lower,
        )
    )


def score_standalone_context(text: str, opening_text: str, closing_text: str) -> tuple[int, list[str]]:
    lower = text.lower()
    opening_lower = opening_text.lower().strip()
    closing_lower = closing_text.lower()
    score = 0
    reasons: list[str] = []

    if not starts_weak(opening_text):
        score += 10
        reasons.append("inicio independente")
    else:
        score -= 18
        reasons.append("inicio depende do contexto anterior")

    if any(term in opening_lower[:180] for term in STANDALONE_TERMS):
        score += 10
        reasons.append("tema claro nos primeiros segundos")
    if any(term in lower for term in COMMENT_TERMS):
        score += 8
        reasons.append("abre espaco para comentario")
    if any(term in closing_lower for term in CLOSING_TERMS):
        score += 8
        reasons.append("tem fechamento")
    if lower.count(" isso ") + lower.count(" aquilo ") + lower.count(" ele ") + lower.count(" eles ") > 8:
        score -= 8
        reasons.append("muitos referentes soltos")
    return score, reasons


def parse_vtt(path: Path) -> list[CaptionLine]:
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    captions: list[CaptionLine] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if "-->" not in line:
            i += 1
            continue

        start_raw, end_raw = [part.strip().split(" ")[0] for part in line.split("-->")[:2]]
        text_parts: list[str] = []
        i += 1
        while i < len(lines) and lines[i].strip():
            text_parts.append(lines[i].strip())
            i += 1

        text = clean_caption_text(" ".join(text_parts))
        if text and (not captions or captions[-1].text != text):
            captions.append(CaptionLine(timestamp_to_seconds(start_raw), timestamp_to_seconds(end_raw), text))
        i += 1
    return captions


def download_subtitles(url: str, lang: str) -> Path:
    WORK.mkdir(parents=True, exist_ok=True)
    video_id_match = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{6,})", url)
    if video_id_match:
        video_id = video_id_match.group(1)
        cached = sorted(WORK.glob(f"*{video_id}*.vtt"), key=lambda path: path.stat().st_mtime, reverse=True)
        if cached:
            return cached[0]

    before = {path.resolve() for path in WORK.glob("*.vtt")}
    run(
        [
            sys.executable,
            "-m",
            "yt_dlp",
            "--no-playlist",
            "--skip-download",
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs",
            lang,
            "--convert-subs",
            "vtt",
            "-o",
            str(WORK / "%(title).120s-%(id)s.%(ext)s"),
            url,
        ],
        check=False,
    )
    after = sorted(
        [path for path in WORK.glob("*.vtt") if path.resolve() not in before],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not after:
        after = sorted(WORK.glob("*.vtt"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not after:
        raise RuntimeError("Nao encontrei legenda ou auto-legenda nesse video. Tente outro video ou baixe uma transcricao.")
    return after[0]


def window_text(captions: list[CaptionLine], start: float, end: float) -> str:
    return clean_joined_transcript(" ".join(line.text for line in captions if line.start < end and line.end > start))


def first_words(text: str, count: int = 10) -> str:
    return " ".join(text.strip().split()[:count])


def opening_boundary_score(captions: list[CaptionLine], start: float, end: float) -> tuple[int, str]:
    opening = window_text(captions, start, min(start + 7, end))
    first = normalize_for_match(first_words(opening, 10))
    score = 0
    reasons: list[str] = []

    if not opening or len(opening.split()) < 7:
        return -80, "inicio sem fala suficiente"

    if starts_weak(opening):
        score -= 45
        reasons.append("inicio quebrado")

    weak_first_patterns = [
        r"^(e|eh|e|ai|ne|entao|dai|cara|tipo|pois|beleza|verdade|exato|sim|nao|fechou|incrivel|mas|ta|falou|falei|sozinho|parada)\b",
        r"^(prolabore|so que|aqui|ali|la|em companhias|desse|daquele|dai|entao|da bolha|por falar|com os caras|vou contar)\b",
        r"^(eu comecei|eu nasci|2012 quando|2012)\b",
        r"^\w+\s+(dele|dela|deles|delas|isso|esse|essa|aquele|aquela)\b",
        r"^(foi|era|tava|estava|tinha|teve)\s+(um|uma|esse|essa|aquela|aquele)\b",
    ]
    if any(re.search(pattern, first) for pattern in weak_first_patterns):
        score -= 35
        reasons.append("primeiras palavras parecem continuacao")

    strong_patterns = [
        r"\b(o problema|o ponto|a verdade|na verdade|o que acontece|quer dizer|imagina|presta atencao)\b",
        r"\b(na hora que|se voce|quando voce|porque voce|por que|ninguem|ninguem fala|isso muda)\b",
        r"\b(empresa|startup|gestao|gestao 4 0|inovacao|faturamento|dinheiro|poder|mercado|brasil|china|eua|ia)\b",
    ]
    strong_hits = sum(1 for pattern in strong_patterns if re.search(pattern, normalize_for_match(opening)))
    if strong_hits:
        score += min(45, strong_hits * 18)
        reasons.append("entrada com assunto claro")
    else:
        score -= 18
        reasons.append("entrada sem assunto forte")

    if "?" in opening[:220]:
        score += 12
        reasons.append("pergunta cedo")

    if opening.strip()[:1].islower():
        score -= 10
        reasons.append("texto parece continuar frase anterior")

    is_ad, ad_reason = is_commercial_candidate(opening, opening)
    if is_ad:
        score -= 80
        reasons.append(ad_reason)
    is_weak_context, weak_context_reason = is_low_value_context(opening, opening)
    if is_weak_context:
        score -= 65
        reasons.append(weak_context_reason)

    return score, ", ".join(reasons) or "entrada aceitavel"


def candidate_opening_starts(captions: list[CaptionLine], start: float, search_until: float) -> list[float]:
    values = {start}
    for caption in captions:
        if start - 0.2 <= caption.start <= search_until:
            values.add(caption.start)
    return sorted(values)


def best_opening_start(
    captions: list[CaptionLine],
    start: float,
    duration: float,
    first: float,
    last: float,
    max_shift: float = 12.0,
) -> tuple[float, int, str]:
    best_start = start
    best_score, best_reason = opening_boundary_score(captions, start, min(start + duration, last))
    search_until = min(start + max_shift, last - duration)
    for option in candidate_opening_starts(captions, start, search_until):
        option = max(first, min(option, last - duration))
        score, reason = opening_boundary_score(captions, option, min(option + duration, last))
        shift = option - start
        if shift > 0.5:
            score += min(10, int(shift))
        if score > best_score + 6:
            best_start = option
            best_score = score
            best_reason = reason
    return best_start, best_score, best_reason


def make_headline(text: str) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    candidates = [strip_weak_prefix(item) for item in sentences[:6] if strip_weak_prefix(item)]
    chosen = max(
        candidates or [strip_weak_prefix(text) or text],
        key=lambda item: (
            sum(word in item.lower() for word in HOOK_WORDS),
            sum(term in item.lower() for term in STANDALONE_TERMS),
            not starts_weak(item),
            -abs(len(item.split()) - 9),
        ),
    )
    chosen = collapse_repeated_chunks(re.sub(r"\s+", " ", chosen).strip())
    words = chosen.split()[:11]
    headline = trim_weak_ending(" ".join(words))
    return headline.upper().rstrip(".,;:") or "O DETALHE QUE MUDA O TABULEIRO"


def score_window(text: str, duration: float) -> tuple[int, str]:
    lower = text.lower()
    opening_text = " ".join(text.split()[:36])
    closing_text = " ".join(text.split()[-42:])
    score = 0
    reasons: list[str] = []
    is_ad, ad_reason = is_commercial_candidate(text, opening_text)
    is_weak_context, weak_context_reason = is_low_value_context(text, opening_text)
    thesis_bonus, thesis_reason = thesis_score(text, opening_text)
    chatter_penalty, chatter_reason = weak_chatter_score(text, opening_text)

    hook_hits = sum(1 for word in HOOK_WORDS if word in lower)
    tension_hits = sum(1 for word in TENSION_WORDS if word in lower)
    question_hits = text.count("?")
    number_hits = len(re.findall(r"\b\d+[%\w.,]*\b", text))

    if 45 <= duration <= 90:
        score += 18
        reasons.append("duracao boa para TikTok")
    if hook_hits:
        score += min(30, hook_hits * 5)
        reasons.append("tema forte")
    if tension_hits:
        score += min(22, tension_hits * 4)
        reasons.append("tem contraste/conflito")
    if question_hits:
        score += min(12, question_hits * 6)
        reasons.append("gera curiosidade")
    if number_hits:
        score += min(10, number_hits * 3)
        reasons.append("tem numeros/dados")
    if any(phrase in lower for phrase in ["nao e", "não é", "o que acontece", "o ponto e", "o ponto é"]):
        score += 10
        reasons.append("tem virada de raciocinio")
    if thesis_bonus:
        score += thesis_bonus
        reasons.append(f"tese forte: {thesis_reason}")
    if chatter_penalty:
        score -= chatter_penalty
        reasons.append(chatter_reason)
    if any(phrase in lower[:260] for phrase in ["ele é especialista", "ela é especialista", "convidado", "podcast", "prazer estar aqui", "mas o nome", "mostra tá certo", "mostra ta certo"]):
        score -= 14
        reasons.append("inicio parece apresentacao, nao corte viral")
    if is_ad:
        score -= 70
        reasons.append(ad_reason)
    if is_weak_context:
        score -= 55
        reasons.append(weak_context_reason)
    if starts_weak(opening_text):
        score -= 18
        reasons.append("inicio fragmentado")
    context_score, context_reasons = score_standalone_context(text, opening_text, closing_text)
    score += context_score
    reasons.extend(context_reasons)
    if len(text.split()) < 70:
        score -= 12
    if len(text.split()) > 230:
        score -= 8

    return max(0, min(100, score)), ", ".join(reasons) or "trecho claro"


def score_opening_window(text: str, duration: float) -> tuple[int, str]:
    lower = text.lower()
    words = text.split()
    score = 18
    reasons: list[str] = []
    is_ad, ad_reason = is_commercial_candidate(text, text)
    is_weak_context, weak_context_reason = is_low_value_context(text, text)
    thesis_bonus, thesis_reason = thesis_score(text, text)
    chatter_penalty, chatter_reason = weak_chatter_score(text, text)

    hook_hits = sum(1 for word in HOOK_WORDS if word in lower)
    opening_hits = sum(1 for word in OPENING_WORDS if word in lower)
    tension_hits = sum(1 for word in TENSION_WORDS if word in lower)
    number_hits = len(re.findall(r"\b\d+[%\w.,]*\b", text))

    if 14 <= len(words) <= 45:
        score += 14
        reasons.append("comeca direto")
    elif len(words) < 9:
        score -= 10
        reasons.append("inicio curto demais")
    elif len(words) > 60:
        score -= 8
        reasons.append("inicio demora a chegar")

    if hook_hits:
        score += min(24, hook_hits * 8)
        reasons.append("tema forte no inicio")
    if opening_hits:
        score += min(18, opening_hits * 6)
        reasons.append("frase de abertura prende")
    if tension_hits:
        score += min(18, tension_hits * 6)
        reasons.append("tensao ja aparece no inicio")
    if "?" in text:
        score += 12
        reasons.append("abre pergunta")
    if number_hits:
        score += min(10, number_hits * 5)
        reasons.append("dado aparece cedo")
    if any(phrase in lower for phrase in ["mas", "so que", "só que", "na verdade", "o problema"]):
        score += 10
        reasons.append("tem virada rapida")
    if thesis_bonus:
        score += min(24, thesis_bonus)
        reasons.append(f"tese cedo: {thesis_reason}")
    if chatter_penalty:
        score -= chatter_penalty
        reasons.append(chatter_reason)
    if starts_weak(text):
        score -= 34
        reasons.append("comeca com frase solta")
    if is_ad:
        score -= 70
        reasons.append(ad_reason)
    if is_weak_context:
        score -= 55
        reasons.append(weak_context_reason)
    if any(term in lower[:160] for term in STANDALONE_TERMS):
        score += 12
        reasons.append("contexto claro rapido")
    elif not (hook_hits or number_hits or "?" in text):
        score -= 10
        reasons.append("sem contexto claro no inicio")

    if duration < 4:
        score -= 8
    return max(0, min(100, score)), ", ".join(reasons) or "inicio neutro"


def combine_text_and_opening_score(text_score: int, hook_score: int) -> int:
    score = round(text_score * 0.62 + hook_score * 0.38)
    if hook_score >= 75:
        score += 8
    elif hook_score >= 62:
        score += 4
    elif hook_score < 35:
        score -= 12
    elif hook_score < 48:
        score -= 6
    return max(0, min(100, score))


def score_candidate_window(
    captions: list[CaptionLine],
    start: float,
    end: float,
) -> tuple[int, int, str, str, str]:
    text = window_text(captions, start, end)
    base_score, reason = score_window(text, end - start)
    opening_text = window_text(captions, start, min(start + 8, end))
    hook_score, hook_reason = score_opening_window(opening_text, min(8, end - start))
    boundary_score, boundary_reason = opening_boundary_score(captions, start, end)
    if boundary_score < -20:
        hook_score = max(0, hook_score + boundary_score)
    elif boundary_score > 15:
        hook_score = min(100, hook_score + min(18, boundary_score // 3))
    hook_reason = f"{hook_reason}; entrada: {boundary_reason}"
    score = combine_text_and_opening_score(base_score, hook_score)
    return score, hook_score, reason, hook_reason, text


def extract_audio_energy(video_path: Path) -> list[float]:
    WORK.mkdir(parents=True, exist_ok=True)
    wav_path = WORK / "audio-analysis.wav"
    run(
        [
            ffmpeg_path(),
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(wav_path),
        ]
    )

    energies: list[float] = []
    with wave.open(str(wav_path), "rb") as wav_file:
        rate = wav_file.getframerate()
        width = wav_file.getsampwidth()
        frames_per_second = rate
        while True:
            raw = wav_file.readframes(frames_per_second)
            if not raw:
                break
            sample_count = len(raw) // width
            if sample_count == 0:
                energies.append(0.0)
                continue
            values: list[int] = []
            for i in range(0, len(raw), width):
                values.append(int.from_bytes(raw[i : i + width], "little", signed=True))
            rms = math.sqrt(sum(value * value for value in values) / max(len(values), 1))
            energies.append(rms / 32768.0)
    return energies


def detect_scene_times(video_path: Path) -> list[float]:
    result = run_capture(
        [
            ffmpeg_path(),
            "-hide_banner",
            "-i",
            str(video_path),
            "-vf",
            "scale=320:-1,select='gt(scene,0.26)',showinfo",
            "-an",
            "-f",
            "null",
            "-",
        ]
    )
    text = (result.stderr or "") + "\n" + (result.stdout or "")
    return [float(match) for match in re.findall(r"pts_time:([0-9.]+)", text)]


def build_media_signals(video_path: Path) -> MediaSignals:
    print("Analisando energia do audio...")
    audio_energy = extract_audio_energy(video_path)
    print("Analisando movimento visual e mudancas de cena...")
    scene_times = detect_scene_times(video_path)
    return MediaSignals(audio_energy=audio_energy, scene_times=scene_times)


def score_media_window(signals: MediaSignals, start: float, end: float) -> tuple[int, str, dict[str, float]]:
    start_i = max(0, int(start))
    end_i = min(len(signals.audio_energy), max(start_i + 1, int(end)))
    window = signals.audio_energy[start_i:end_i]
    hook_end_i = min(len(signals.audio_energy), max(start_i + 1, int(start + 5)))
    hook_window = signals.audio_energy[start_i:hook_end_i]
    all_energy = [value for value in signals.audio_energy if value > 0]
    global_avg = sum(all_energy) / max(len(all_energy), 1)

    if not window:
        return 0, "sem audio analisavel", {}

    avg = sum(window) / len(window)
    peak = max(window)
    variance = sum((value - avg) ** 2 for value in window) / len(window)
    std = math.sqrt(variance)
    silence_threshold = max(0.006, global_avg * 0.35)
    silence_ratio = sum(1 for value in window if value < silence_threshold) / len(window)
    hook_avg = sum(hook_window) / max(len(hook_window), 1)
    hook_silence_ratio = sum(1 for value in hook_window if value < silence_threshold) / max(len(hook_window), 1)
    scene_count = sum(1 for time in signals.scene_times if start <= time <= end)
    hook_scene_count = sum(1 for time in signals.scene_times if start <= time <= min(end, start + 5))
    scenes_per_minute = scene_count / max((end - start) / 60.0, 0.1)

    score = 0
    reasons: list[str] = []

    if avg >= global_avg * 1.05:
        score += 10
        reasons.append("voz com energia acima da media")
    if hook_avg >= global_avg * 1.10:
        score += 8
        reasons.append("primeiros segundos com energia")
    if hook_silence_ratio > 0.35:
        score -= 10
        reasons.append("inicio com silencio demais")
    if peak >= global_avg * 1.8:
        score += 8
        reasons.append("tem picos de intensidade")
    if std >= global_avg * 0.35:
        score += 8
        reasons.append("fala com variacao, menos monotona")
    if 0.03 <= silence_ratio <= 0.22:
        score += 8
        reasons.append("pausas naturais sem ficar parado")
    elif silence_ratio > 0.35:
        score -= 8
        reasons.append("muitas pausas/silencio")
    if 1 <= scenes_per_minute <= 10:
        score += 8
        reasons.append("tem mudanca visual moderada")
    if hook_scene_count:
        score += 4
        reasons.append("mudanca visual cedo")
    elif scenes_per_minute > 10:
        score += 4
        reasons.append("muita mudanca visual")
    elif scene_count == 0:
        score -= 4
        reasons.append("pouca mudanca visual detectada")

    metrics = {
        "audio_avg": round(avg, 5),
        "audio_peak": round(peak, 5),
        "audio_variation": round(std, 5),
        "hook_audio_avg": round(hook_avg, 5),
        "hook_silence_ratio": round(hook_silence_ratio, 3),
        "hook_scene_count": float(hook_scene_count),
        "silence_ratio": round(silence_ratio, 3),
        "scene_count": float(scene_count),
        "scenes_per_minute": round(scenes_per_minute, 2),
    }
    return max(-15, min(35, score)), ", ".join(reasons) or "midia neutra", metrics


def apply_media_scores(candidates: list[Candidate], signals: MediaSignals | None) -> list[Candidate]:
    if signals is None:
        return candidates
    rescored: list[Candidate] = []
    for candidate in candidates:
        media_score, media_reason, metrics = score_media_window(signals, candidate.start, candidate.end)
        total = max(0, min(100, candidate.text_score + media_score))
        rescored.append(
            Candidate(
                score=total,
                start=candidate.start,
                end=candidate.end,
                headline=candidate.headline,
                reason=f"{candidate.reason}; midia: {media_reason}",
                text=candidate.text,
                text_score=candidate.text_score,
                hook_score=candidate.hook_score,
                hook_reason=candidate.hook_reason,
                start_adjustment=candidate.start_adjustment,
                media_score=media_score,
                media_metrics=metrics,
            )
        )
    rescored.sort(key=lambda item: item.score, reverse=True)
    return rescored


def optimize_candidate_starts(
    candidates: list[Candidate],
    captions: list[CaptionLine],
    signals: MediaSignals | None,
    first: float,
    last: float,
) -> list[Candidate]:
    optimized: list[Candidate] = []
    caption_starts = [line.start for line in captions]

    for candidate in candidates:
        duration = candidate.end - candidate.start
        possible_starts = {candidate.start}
        for offset in range(-10, 11, 2):
            possible_starts.add(candidate.start + offset)
        for caption_start in caption_starts:
            if candidate.start - 10 <= caption_start <= candidate.start + 10:
                possible_starts.add(caption_start)
        best_entry, _, _ = best_opening_start(captions, candidate.start, duration, first, last)
        possible_starts.add(best_entry)

        best = candidate
        best_sort = (candidate.score, candidate.hook_score, -abs(candidate.start_adjustment))
        for start in sorted(possible_starts):
            start = max(first, min(start, last - duration))
            end = min(start + duration, last)
            if end - start < 45:
                continue
            score, hook_score, reason, hook_reason, text = score_candidate_window(captions, start, end)
            is_ad, _ = is_commercial_candidate(text, window_text(captions, start, min(start + 12, end)))
            if is_ad:
                continue
            is_weak_context, _ = is_low_value_context(text, window_text(captions, start, min(start + 12, end)))
            if is_weak_context:
                continue
            if hook_score < 45:
                continue
            if len(text.split()) < 45:
                continue
            media_score = 0
            media_reason = "midia nao analisada"
            metrics: dict[str, float] = {}
            if signals is not None:
                media_score, media_reason, metrics = score_media_window(signals, start, end)
            total = max(0, min(100, score + media_score))
            adjustment = start - candidate.start
            boundary_score, boundary_reason = opening_boundary_score(captions, start, end)
            if boundary_score > 15:
                total = min(100, total + min(8, boundary_score // 8))
            candidate_sort = (total, hook_score, -abs(adjustment))
            if candidate_sort > best_sort:
                adjustment_note = ""
                if abs(adjustment) >= 0.5:
                    direction = "adiantada" if adjustment < 0 else "atrasada"
                    adjustment_note = f"; entrada {direction} em {abs(adjustment):.1f}s para melhorar o gancho"
                entry_note = f"; entrada limpa: {boundary_reason}"
                best = Candidate(
                    score=total,
                    start=start,
                    end=end,
                    headline=editorial_title(text, text),
                    reason=f"{reason}; inicio: {hook_reason}; midia: {media_reason}{adjustment_note}{entry_note}",
                    text=text,
                    text_score=score,
                    hook_score=hook_score,
                    hook_reason=hook_reason,
                    start_adjustment=adjustment,
                    media_score=media_score,
                    media_metrics=metrics,
                )
                best_sort = candidate_sort
        optimized.append(best)

    optimized.sort(key=lambda item: item.score, reverse=True)
    return optimized


def find_candidates(
    captions: list[CaptionLine],
    min_duration: int,
    max_duration: int,
    top: int,
    signals: MediaSignals | None = None,
) -> list[Candidate]:
    if not captions:
        return []

    first = captions[0].start
    last = captions[-1].end
    candidates: list[Candidate] = []
    step = 15

    current = first
    while current + min_duration <= last:
        for duration in range(min_duration, max_duration + 1, 15):
            end = min(current + duration, last)
            text = window_text(captions, current, end)
            if len(text.split()) < 45:
                continue
            current_for_score = current
            end_for_score = end
            boundary_score, boundary_reason = opening_boundary_score(captions, current_for_score, end_for_score)
            if boundary_score < -25:
                continue
            score, hook_score, reason, hook_reason, text = score_candidate_window(captions, current_for_score, end_for_score)
            if boundary_score > 15:
                score = min(100, score + min(8, boundary_score // 8))
            is_ad, _ = is_commercial_candidate(text, window_text(captions, current_for_score, min(current_for_score + 12, end_for_score)))
            if is_ad:
                continue
            is_weak_context, _ = is_low_value_context(text, window_text(captions, current_for_score, min(current_for_score + 12, end_for_score)))
            if is_weak_context:
                continue
            if hook_score < 45:
                continue
            candidates.append(
                Candidate(
                    score=score,
                    start=current_for_score,
                    end=end_for_score,
                    headline=editorial_title(text, text),
                    reason=f"{reason}; inicio: {hook_reason}; entrada limpa: {boundary_reason}",
                    text=text,
                    text_score=score,
                    hook_score=hook_score,
                    hook_reason=hook_reason,
                    start_adjustment=current_for_score - current,
                )
            )
        current += step

    candidates = apply_media_scores(candidates, signals)
    candidates = optimize_candidate_starts(candidates[: max(top * 6, top)], captions, signals, first, last)
    candidates.sort(key=lambda item: item.score, reverse=True)
    filtered: list[Candidate] = []
    for candidate in candidates:
        overlaps = any(
            max(candidate.start, chosen.start) < min(candidate.end, chosen.end) - 20
            for chosen in filtered
        )
        if not overlaps:
            filtered.append(candidate)
        if len(filtered) >= top:
            break
    return filtered


def write_report(candidates: list[Candidate], source: str) -> Path:
    OUTPUTS.mkdir(exist_ok=True)
    out_dir = OUTPUTS / "viral-moments"
    out_dir.mkdir(exist_ok=True)
    report = out_dir / "candidatos-virais.md"
    data = {
        "source": source,
        "candidates": [
            {
                "score": item.score,
                "text_score": item.text_score,
                "hook_score": item.hook_score,
                "hook_reason": item.hook_reason,
                "start_adjustment": round(item.start_adjustment, 2),
                "media_score": item.media_score,
                "editorial_score": item.editorial_score,
                "classification": classify_score(item.score),
                "start": seconds_to_timestamp(item.start),
                "duration": int(item.end - item.start),
                "headline": item.headline,
                "reason": item.reason,
                "editorial_reason": item.editorial_reason,
                "media_metrics": item.media_metrics or {},
                "first_sentence": first_sentence(item.text),
                "decision": approval_decision(item.score, item.hook_score, item.reason),
                "preview": item.text[:700],
            }
            for item in candidates
        ],
    }
    json_path = out_dir / "candidatos-virais.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [f"# Candidatos virais\n\nFonte: {source}\n"]
    for index, item in enumerate(candidates, start=1):
        lines.extend(
            [
                f"\n## {index}. Score {item.score}/100 - {classify_score(item.score)} - {seconds_to_timestamp(item.start)} ({int(item.end - item.start)}s)\n",
                f"Decisao: {approval_decision(item.score, item.hook_score, item.reason)}\n\n",
                f"Headline: {item.headline}\n\n",
                f"Primeira frase: {first_sentence(item.text)}\n\n",
                f"Por que pode funcionar: {item.reason}\n\n",
                f"Breakdown: texto+inicio {item.text_score}/100 | gancho inicial {item.hook_score}/100 | midia {item.media_score:+d} = {item.score}/100\n\n",
                f"Ajuste de entrada: {item.start_adjustment:+.1f}s\n\n",
                f"Editorial IA: {item.editorial_score}/100 - {item.editorial_reason}\n\n",
                f"Metricas de midia: {json.dumps(item.media_metrics or {}, ensure_ascii=False)}\n\n",
                "Previa:\n\n",
                f"> {item.text[:900]}\n\n",
                "Comando para cortar:\n\n",
                "```powershell\n",
                (
                    ".\\.venv\\Scripts\\python.exe .\\src\\youtube_to_cut.py "
                    f"--url \"{source}\" --start \"{seconds_to_timestamp(item.start)}\" "
                    f"--duration {int(item.end - item.start)} --headline \"{item.headline}\"\n"
                ),
                "```\n",
            ]
        )
    write_user_text(report, "".join(lines))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Analisa um video do YouTube e sugere trechos com potencial viral.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--lang", default="pt-orig,pt", help="Idiomas de legenda do yt-dlp.")
    parser.add_argument("--min-duration", type=int, default=45)
    parser.add_argument("--max-duration", type=int, default=90)
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--no-media-analysis", action="store_true", help="Usa apenas legenda/transcricao, sem audio e video.")
    args = parser.parse_args()

    subtitle_path = download_subtitles(args.url, args.lang)
    captions = parse_vtt(subtitle_path)
    signals = None
    if not args.no_media_analysis:
        try:
            video_path = download_youtube(args.url)
            signals = build_media_signals(video_path)
        except Exception as exc:
            print(f"[aviso] Analise de midia falhou; seguindo apenas com texto. Motivo: {exc}")
    candidates = find_candidates(captions, args.min_duration, args.max_duration, args.top, signals=signals)
    if not candidates:
        raise RuntimeError("Nao encontrei candidatos fortes nessa legenda.")

    report = write_report(candidates, args.url)
    print(f"Relatorio criado: {report}")
    print("Melhores candidatos:")
    for index, item in enumerate(candidates, start=1):
        print(
            f"{index}. score={item.score} start={seconds_to_timestamp(item.start)} "
            f"duration={int(item.end - item.start)} headline={item.headline}"
        )


if __name__ == "__main__":
    main()
