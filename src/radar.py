from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
OUTPUTS = ROOT / "outputs"
SOURCES_PATH = CONFIG / "radar_sources.json"
STATE_PATH = OUTPUTS / "radar_state.json"
TREND_CACHE_PATH = OUTPUTS / "trend_cache.json"
TREND_CACHE_TTL_SECONDS = 6 * 60 * 60

YT_NS = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}


@dataclass
class RadarSource:
    id: str
    name: str
    channel_id: str
    url: str
    content_type: str = "podcast"
    enabled: bool = True
    auto_cut: bool = False
    created_at: str = ""

    @property
    def feed_url(self) -> str:
        return f"https://www.youtube.com/feeds/videos.xml?channel_id={self.channel_id}"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def source_id(channel_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "", channel_id)[-32:]


def default_sources() -> list[dict[str, Any]]:
    return []


def load_sources() -> list[RadarSource]:
    data = load_json(SOURCES_PATH, default_sources())
    sources: list[RadarSource] = []
    for item in data:
        channel_id = str(item.get("channel_id", "")).strip()
        if not channel_id:
            continue
        sources.append(
            RadarSource(
                id=str(item.get("id") or source_id(channel_id)),
                name=str(item.get("name") or channel_id),
                channel_id=channel_id,
                url=str(item.get("url") or ""),
                content_type=normalize_content_type(str(item.get("content_type") or item.get("type") or "podcast")),
                enabled=bool(item.get("enabled", True)),
                auto_cut=bool(item.get("auto_cut", False)),
                created_at=str(item.get("created_at") or ""),
            )
        )
    return sources


def save_sources(sources: list[RadarSource]) -> None:
    save_json(SOURCES_PATH, [source.__dict__ for source in sources])


def normalize_content_type(value: str) -> str:
    clean = str(value or "").strip().lower()
    if clean in {"short", "shorts", "clip", "clips"}:
        return "shorts"
    return "podcast"


def infer_content_type(title: str, url: str, duration: int | float | None = None, default: str = "podcast") -> str:
    text = f"{title} {url}".lower()
    if "/shorts/" in text or "#shorts" in text or " shorts" in text:
        return "shorts"
    if duration is not None and duration > 0:
        return "shorts" if duration < 300 else "podcast"
    return normalize_content_type(default)


def extract_trend_queries(title: str) -> list[str]:
    text = re.sub(r"\s+", " ", str(title or "").strip())
    lower = text.lower()
    queries: list[str] = []
    phrases = [
        "banco master",
        "bradesco",
        "china",
        "eua",
        "trump",
        "lula",
        "bolsonaro",
        "pt",
        "cpi",
        "guerra",
        "eleicao",
        "eleição",
        "crime organizado",
        "policia federal",
        "pf",
        "operacao",
        "operação",
        "geopolitica",
        "geopolítica",
    ]
    for phrase in phrases:
        if contains_term(lower, phrase) and phrase not in queries:
            queries.append(phrase)
    for part in re.split(r"\s+\+\s+|\s+-\s+|\s+vs\s+|\s+x\s+", text, flags=re.IGNORECASE):
        clean = re.sub(r"\bFlow(?: News)?\s*#?\d+\b", "", part, flags=re.IGNORECASE)
        clean = re.sub(r"[^A-Za-zÀ-ÿ0-9 ]+", " ", clean)
        clean = re.sub(r"\s+", " ", clean).strip()
        words = clean.split()
        if 2 <= len(words) <= 5 and 6 <= len(clean) <= 48:
            query = clean.lower()
            if query not in queries:
                queries.append(query)
    return queries[:3]


def parse_rss_date(value: str) -> float:
    if not value:
        return 0.0
    try:
        from email.utils import parsedate_to_datetime

        return parsedate_to_datetime(value).timestamp()
    except Exception:
        return 0.0


def fetch_news_trend(query: str) -> dict[str, Any]:
    quoted = urllib.parse.quote_plus(f'"{query}" when:7d')
    url = f"https://news.google.com/rss/search?q={quoted}&hl=pt-BR&gl=BR&ceid=BR:pt-419"
    try:
        xml = http_get(url, timeout=12)
        root = ET.fromstring(xml)
    except Exception:
        return {"score": 0, "count": 0, "top_titles": [], "updated_at": time.time()}
    now = time.time()
    weighted = 0
    titles: list[str] = []
    for entry in root.findall(".//item")[:12]:
        title = (entry.findtext("title") or "").strip()
        pub_ts = parse_rss_date(entry.findtext("pubDate") or "")
        age_days = (now - pub_ts) / 86400 if pub_ts else 9
        if age_days <= 1:
            weighted += 4
        elif age_days <= 3:
            weighted += 3
        elif age_days <= 7:
            weighted += 1
        if title:
            titles.append(title)
    return {
        "score": clamp_score(min(22, weighted)),
        "count": len(titles),
        "top_titles": titles[:3],
        "updated_at": now,
    }


def load_trend_cache() -> dict[str, Any]:
    data = load_json(TREND_CACHE_PATH, {"queries": {}})
    if "queries" not in data or not isinstance(data["queries"], dict):
        return {"queries": {}}
    return data


def trend_signal_for_title(title: str, cache: dict[str, Any] | None = None) -> dict[str, Any]:
    cache = cache or load_trend_cache()
    best = {"score": 0, "query": "", "count": 0}
    for query in extract_trend_queries(title):
        data = cache.get("queries", {}).get(query)
        if not data:
            continue
        score = int(data.get("score") or 0)
        if score > int(best["score"]):
            best = {"score": score, "query": query, "count": int(data.get("count") or 0)}
    return best


def refresh_trends_for_items(items: list[dict[str, Any]], max_queries: int = 24) -> None:
    cache = load_trend_cache()
    queries = cache.setdefault("queries", {})
    wanted: list[str] = []
    for item in sorted(items, key=lambda value: int(value.get("episode_score") or 0), reverse=True):
        for query in extract_trend_queries(str(item.get("title") or "")):
            if query not in wanted:
                wanted.append(query)
        if len(wanted) >= max_queries:
            break
    now = time.time()
    changed = False
    for query in wanted[:max_queries]:
        cached = queries.get(query, {})
        if now - float(cached.get("updated_at") or 0) < TREND_CACHE_TTL_SECONDS:
            continue
        queries[query] = fetch_news_trend(query)
        changed = True
    if changed:
        save_json(TREND_CACHE_PATH, cache)


def clamp_score(value: int) -> int:
    return max(0, min(100, int(value)))


def contains_term(text: str, term: str) -> bool:
    if len(term) <= 4 and " " not in term:
        return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, flags=re.IGNORECASE) is not None
    return term in text


def score_episode(item: dict[str, Any]) -> dict[str, Any]:
    title = str(item.get("title") or "")
    text = title.lower()
    content_type = str(item.get("content_type") or "podcast")
    duration = float(item.get("duration") or 0)
    published_ts = float(item.get("published_ts") or 0)
    age_days = (time.time() - published_ts) / 86400 if published_ts > 0 else None
    score = 35
    reasons: list[str] = []
    parts: list[dict[str, Any]] = [{"label": "Base editorial", "value": 35}]

    def add_part(label: str, value: int, reason: str = "") -> None:
        nonlocal score
        score += value
        parts.append({"label": label, "value": value})
        if reason:
            reasons.append(reason)

    if content_type == "podcast":
        add_part("Podcast completo", 12, "podcast completo")
    if age_days is not None:
        if age_days <= 2:
            add_part("Recencia", 18, "muito recente")
        elif age_days <= 7:
            add_part("Recencia", 13, "recente")
        elif age_days <= 15:
            add_part("Recencia", 8, "dentro dos 15 dias")
        else:
            add_part("Recencia", -10, "fora da janela ideal")
    else:
        add_part("Data", -4, "data incerta")

    if duration >= 5400:
        add_part("Duracao", 12, "duracao forte para varios cortes")
    elif duration >= 2700:
        add_part("Duracao", 8, "duracao boa")
    elif 300 <= duration < 1200:
        add_part("Duracao", -6, "curto para podcast")

    power_terms = [
        "china",
        "eua",
        "trump",
        "lula",
        "bolsonaro",
        "pt",
        "banco",
        "master",
        "bradesco",
        "crime",
        "pf",
        "operação",
        "operacao",
        "cpi",
        "guerra",
        "poder",
        "política",
        "politica",
        "economia",
        "eleição",
        "eleicao",
        "presidência",
        "presidencia",
        "geopolítica",
        "geopolitica",
    ]
    matched = [term for term in power_terms if contains_term(text, term)]
    if matched:
        theme_bonus = min(20, 5 + len(set(matched)) * 3)
        add_part("Tema quente", theme_bonus, "tema quente: " + ", ".join(sorted(set(matched))[:3]))

    trend = trend_signal_for_title(title)
    trend_bonus = int(trend.get("score") or 0)
    if trend_bonus:
        add_part("Trend noticias", trend_bonus, f"noticias em alta: {trend.get('query')} +{trend_bonus}")

    if re.search(r"\bflow\s*#\d+|\bflow news\s*#\d+", text):
        add_part("Formato", 7, "formato recorrente forte")
    if any(mark in title for mark in ("+", " x ", " X ", " vs ", " VS ")):
        add_part("Conflito/convidados", 4, "confronto ou convidados")
    if len(title) >= 90:
        add_part("Titulo longo", -5, "titulo longo")
    if "members" in text:
        add_part("Restricao", -12, "conteudo possivelmente restrito")
    if "warning" in text or "impersonating" in text:
        add_part("Encaixe editorial", -10, "baixo encaixe editorial")

    final_score = clamp_score(score)
    if final_score >= 85:
        decision = "Prioridade alta"
    elif final_score >= 70:
        decision = "Testar hoje"
    elif final_score >= 55:
        decision = "Baixa prioridade"
    else:
        decision = "Ignorar por enquanto"
    item["episode_score"] = final_score
    item["episode_score_reason"] = "; ".join(reasons[:5])
    item["score_parts"] = parts
    item["editorial_decision"] = decision
    item["trend_score"] = trend_bonus
    item["trend_query"] = str(trend.get("query") or "")
    return item


def enrich_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [score_episode(dict(item)) for item in items]


def get_video_duration(video_url: str) -> int | None:
    try:
        from yt_dlp import YoutubeDL
    except Exception:
        return None
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
    }
    try:
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(video_url, download=False)
    except Exception:
        return None
    if not isinstance(info, dict):
        return None
    duration = info.get("duration")
    try:
        return int(float(duration))
    except (TypeError, ValueError):
        return None


def playlist_url_for(source: RadarSource) -> str:
    base = source.url.rstrip("/")
    if source.content_type == "shorts":
        return base + "/shorts"
    return base + "/streams"


def scan_source_with_ytdlp(source: RadarSource, limit: int = 50) -> list[dict[str, Any]]:
    try:
        from yt_dlp import YoutubeDL
    except Exception:
        return []
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,
        "playlistend": limit,
    }
    try:
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(playlist_url_for(source), download=False)
    except Exception:
        return []
    entries = info.get("entries") if isinstance(info, dict) else []
    items: list[dict[str, Any]] = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        video_id = str(entry.get("id") or "").strip()
        title = str(entry.get("title") or "").strip()
        url = str(entry.get("url") or "").strip()
        if video_id and not url.startswith("http"):
            url = f"https://www.youtube.com/watch?v={video_id}"
        if not video_id or not url:
            continue
        duration = entry.get("duration")
        try:
            duration = int(float(duration)) if duration not in (None, "") else None
        except (TypeError, ValueError):
            duration = None
        content_type = infer_content_type(title, url, duration=duration, default=source.content_type)
        if source.content_type == "podcast" and content_type == "shorts":
            continue
        timestamp = entry.get("timestamp") or entry.get("release_timestamp")
        published_ts = float(timestamp or 0)
        published = datetime.fromtimestamp(published_ts, tz=timezone.utc).isoformat() if published_ts else ""
        items.append(
            score_episode({
                "id": video_id,
                "source_id": source.id,
                "source_name": source.name,
                "channel_id": source.channel_id,
                "source_type": source.content_type,
                "content_type": content_type,
                "duration": duration,
                "title": title,
                "url": url,
                "published": published,
                "updated": published,
                "published_ts": published_ts,
                "discovered_at": now_iso(),
                "deep_scan": True,
            })
        )
    return items


def http_get(url: str, timeout: int = 18) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PoderEmJogoRadar/1.0",
            "Accept": "application/rss+xml, application/atom+xml, text/xml, text/html",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def resolve_channel_from_html(url: str) -> tuple[str, str]:
    html = http_get(url)
    match = re.search(r'"channelId"\s*:\s*"(UC[a-zA-Z0-9_-]{20,})"', html)
    if not match:
        match = re.search(r'<meta itemprop="channelId" content="(UC[a-zA-Z0-9_-]{20,})"', html)
    if not match:
        raise RuntimeError("Nao consegui encontrar o channel_id nessa URL.")
    channel_id = match.group(1)
    title_match = re.search(r'<meta property="og:title" content="([^"]+)"', html)
    name = title_match.group(1).strip() if title_match else channel_id
    return channel_id, name


def resolve_channel_with_ytdlp(url: str) -> tuple[str, str] | None:
    try:
        from yt_dlp import YoutubeDL
    except Exception:
        return None
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,
        "playlistend": 1,
    }
    try:
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception:
        return None
    if not isinstance(info, dict):
        return None
    channel_id = str(info.get("channel_id") or info.get("uploader_id") or "").strip()
    name = str(info.get("channel") or info.get("uploader") or info.get("title") or channel_id).strip()
    if channel_id.startswith("UC"):
        return channel_id, name
    channel_url = str(info.get("channel_url") or info.get("uploader_url") or "").strip()
    if channel_url and channel_url != url:
        return resolve_channel_with_ytdlp(channel_url)
    return None


def normalize_youtube_url(value: str) -> str:
    value = value.strip()
    if value.startswith("@"):
        return "https://www.youtube.com/" + value
    if value.startswith("UC") and len(value) >= 20:
        return f"https://www.youtube.com/channel/{value}"
    if value.startswith("youtube.com/"):
        return "https://" + value
    return value


def resolve_source(value: str, name: str = "", auto_cut: bool = False, content_type: str = "podcast") -> RadarSource:
    url = normalize_youtube_url(value)
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    channel_id = ""
    if "channel_id" in query:
        channel_id = str(query["channel_id"][0])
    elif "/channel/" in parsed.path:
        channel_id = parsed.path.split("/channel/", 1)[1].split("/", 1)[0]
    if not channel_id:
        resolved = resolve_channel_with_ytdlp(url)
        if resolved:
            channel_id, detected_name = resolved
        else:
            channel_id, detected_name = resolve_channel_from_html(url)
    else:
        detected_name = channel_id
    return RadarSource(
        id=source_id(channel_id),
        name=name.strip() or detected_name,
        channel_id=channel_id,
        url=url,
        content_type=normalize_content_type(content_type),
        enabled=True,
        auto_cut=auto_cut,
        created_at=now_iso(),
    )


def add_source(value: str, name: str = "", auto_cut: bool = False, content_type: str = "podcast") -> RadarSource:
    source = resolve_source(value, name, auto_cut=auto_cut, content_type=content_type)
    sources = load_sources()
    existing = [item for item in sources if item.channel_id == source.channel_id]
    if existing:
        existing[0].auto_cut = auto_cut
        existing[0].content_type = source.content_type
        if name.strip():
            existing[0].name = name.strip()
        save_sources(sources)
        return existing[0]
    sources.insert(0, source)
    save_sources(sources)
    seed_source_baseline(source)
    return source


def parse_date(value: str) -> float:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def scan_source(source: RadarSource, limit: int = 8, classify: bool = False, existing: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    xml = http_get(source.feed_url)
    root = ET.fromstring(xml)
    items: list[dict[str, Any]] = []
    for entry in root.findall("atom:entry", YT_NS)[:limit]:
        video_id = (entry.findtext("yt:videoId", default="", namespaces=YT_NS) or "").strip()
        title = (entry.findtext("atom:title", default="", namespaces=YT_NS) or "").strip()
        published = (entry.findtext("atom:published", default="", namespaces=YT_NS) or "").strip()
        updated = (entry.findtext("atom:updated", default="", namespaces=YT_NS) or "").strip()
        link_el = entry.find("atom:link", YT_NS)
        url = link_el.attrib.get("href", "") if link_el is not None else f"https://www.youtube.com/watch?v={video_id}"
        if not video_id:
            continue
        previous = (existing or {}).get(video_id, {})
        duration = previous.get("duration")
        if classify and duration in (None, "", 0):
            duration = get_video_duration(url)
        content_type = infer_content_type(title, url, duration=duration, default=source.content_type)
        items.append(
            score_episode({
                "id": video_id,
                "source_id": source.id,
                "source_name": source.name,
                "channel_id": source.channel_id,
                "source_type": source.content_type,
                "content_type": content_type,
                "duration": duration,
                "title": title,
                "url": url,
                "published": published,
                "updated": updated,
                "published_ts": parse_date(published or updated),
                "discovered_at": now_iso(),
            })
        )
    if source.content_type == "podcast":
        merged = {item["id"]: item for item in items}
        for item in scan_source_with_ytdlp(source, limit=max(limit, 50)):
            old = merged.get(item["id"], {})
            merged[item["id"]] = {**item, **{key: value for key, value in old.items() if value not in ("", None, 0)}}
        items = sorted(merged.values(), key=lambda item: float(item.get("published_ts") or 0), reverse=True)
    return items[:limit]


def load_state() -> dict[str, Any]:
    return load_json(STATE_PATH, {"items": [], "seen": {}, "last_scan": ""})


def save_state(state: dict[str, Any]) -> None:
    save_json(STATE_PATH, state)


def seed_source_baseline(source: RadarSource, limit: int = 50) -> None:
    """Marca episodios atuais como vistos para o automatico agir so nos proximos lancamentos."""
    state = load_state()
    seen = dict(state.get("seen", {}))
    existing = {str(item.get("id")): item for item in state.get("items", [])}
    try:
        entries = scan_source(source, limit)
    except Exception:
        entries = []
    for entry in entries:
        entry["status"] = existing.get(entry["id"], {}).get("status", "visto")
        entry["is_new"] = False
        existing[entry["id"]] = {**existing.get(entry["id"], {}), **entry}
        seen[entry["id"]] = now_iso()
    base_items = sorted(existing.values(), key=lambda item: float(item.get("published_ts") or 0), reverse=True)[:120]
    refresh_trends_for_items(base_items)
    items = enrich_items(base_items)
    state.update({"items": items, "seen": seen, "last_scan": state.get("last_scan", "")})
    save_state(state)


def scan_all(limit_per_source: int = 50, classify: bool = True) -> dict[str, Any]:
    sources = load_sources()
    state = load_state()
    seen = dict(state.get("seen", {}))
    existing = {str(item.get("id")): item for item in state.get("items", [])}
    errors: list[dict[str, str]] = []
    added = 0
    for source in sources:
        if not source.enabled:
            continue
        try:
            entries = scan_source(source, limit_per_source, classify=classify, existing=existing)
        except (urllib.error.URLError, TimeoutError, RuntimeError, ET.ParseError) as exc:
            errors.append({"source": source.name, "error": str(exc)})
            continue
        for entry in entries:
            was_known = entry["id"] in seen or entry["id"] in existing
            deep_without_date = bool(entry.get("deep_scan")) and not float(entry.get("published_ts") or 0)
            entry["status"] = existing.get(entry["id"], {}).get("status", "visto" if deep_without_date or was_known else "novo")
            entry["is_new"] = False if deep_without_date else not was_known
            if not was_known:
                added += 1
            existing[entry["id"]] = score_episode({**existing.get(entry["id"], {}), **entry})
            seen[entry["id"]] = now_iso()
    base_items = sorted(existing.values(), key=lambda item: float(item.get("published_ts") or 0), reverse=True)[:120]
    refresh_trends_for_items(base_items)
    items = enrich_items(base_items)
    state = {"items": items, "seen": seen, "last_scan": now_iso(), "errors": errors, "added": added}
    save_state(state)
    return {"sources": [source.__dict__ for source in sources], **state}


def mark_item(video_id: str, status: str) -> None:
    state = load_state()
    for item in state.get("items", []):
        if str(item.get("id")) == str(video_id):
            item["status"] = status
            item["updated_status_at"] = now_iso()
            break
    save_state(state)


def read_radar() -> dict[str, Any]:
    sources = [source.__dict__ for source in load_sources()]
    state = load_state()
    state["items"] = enrich_items(list(state.get("items", [])))
    return {"sources": sources, **state}


def main() -> None:
    if len(sys.argv) >= 3 and sys.argv[1] == "add":
        source = add_source(sys.argv[2], " ".join(sys.argv[3:]))
        print(json.dumps(source.__dict__, ensure_ascii=False, indent=2))
        return
    data = scan_all()
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
