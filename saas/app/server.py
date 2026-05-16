from __future__ import annotations

import json
import os
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import parse_qs, quote, unquote, urlparse
from uuid import uuid4

from .db import create_job, create_lead, get_job, init_db, list_jobs, list_leads
from .settings import DEFAULT_USER_ID, MOBILE_WEB, OUTPUTS
from .worker import cancel_job, enqueue_job


HOST = "0.0.0.0"
PORT = int(os.getenv("PORT", "8790"))

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".mp4": "video/mp4",
    ".txt": "text/plain; charset=utf-8",
}

SKIP_OUTPUT_PARTS = {".work", "_validacao", "rejeitados", "saas"}
LEAD_RATE_WINDOW_SECONDS = 10 * 60
LEAD_RATE_MAX_PER_WINDOW = 3
LEAD_MIN_INTERVAL_SECONDS = 12
LEAD_RATE_STATE: dict[str, list[float]] = {}
LEAD_LAST_SUBMISSION_BY_KEY: dict[str, float] = {}
LEAD_BLOCK_EVENTS_BY_IP: dict[str, list[float]] = {}
MAX_JSON_BODY_BYTES = 20_000
SECURITY_ALERT_WINDOW_SECONDS = 5 * 60
SECURITY_ALERT_BLOCK_THRESHOLD = 7
ALLOWED_ORIGINS = {
    origin.strip().rstrip("/")
    for origin in os.getenv(
        "ALLOWED_ORIGINS",
        "https://uardon.com.br,https://www.uardon.com.br,https://uardon-arquitetura-interiores.netlify.app,http://127.0.0.1:8899,http://127.0.0.1:8790,http://localhost:8899,http://localhost:8790",
    ).split(",")
    if origin.strip()
}
TURNSTILE_SECRET_KEY = os.getenv("TURNSTILE_SECRET_KEY", "").strip()


def valid_youtube_url(url: str) -> bool:
    return bool(re.match(r"^https?://", url)) and ("youtube.com/" in url or "youtu.be/" in url)


def normalize_request(data: dict) -> dict:
    url = str(data.get("url") or "").strip()
    if not valid_youtube_url(url):
        raise ValueError("URL do YouTube inválida")
    return {
        "url": url,
        "count": max(1, min(8, int(data.get("count") or 3))),
        "min_score": max(0, min(100, int(data.get("min_score") or 75))),
        "min_duration": max(15, min(180, int(data.get("min_duration") or 45))),
        "max_duration": max(20, min(240, int(data.get("max_duration") or 90))),
        "quality": str(data.get("quality") or "alta") if str(data.get("quality") or "alta") in {"tiktok", "alta", "4k"} else "alta",
        "ai_mode": str(data.get("ai_mode") or "auto") if str(data.get("ai_mode") or "auto") in {"auto", "off", "required"} else "auto",
        "preview_only": bool(data.get("preview_only") or False),
    }


def normalize_lead_request(data: dict) -> dict:
    name = str(data.get("name") or data.get("nome") or "").strip()
    phone = str(data.get("phone") or data.get("telefone") or "").strip()
    city = str(data.get("city") or data.get("cidade") or "").strip()
    project_type = str(data.get("project_type") or data.get("tipo") or "").strip()
    message = str(data.get("message") or data.get("msg") or "").strip()
    source = str(data.get("source") or "landing-page").strip() or "landing-page"
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    honeypot = str(data.get("company_site") or data.get("website") or "").strip()
    if len(name) < 2:
        raise ValueError("Nome inválido")
    if honeypot:
        raise ValueError("Envio inválido")
    normalized_phone = normalize_whatsapp(phone)
    if not normalized_phone:
        raise ValueError("WhatsApp inválido. Use DDD + 9 números.")
    return {
        "name": name[:120],
        "phone": normalized_phone,
        "city": city[:120],
        "project_type": project_type[:120],
        "message": message[:2000],
        "source": source[:120],
        "metadata": metadata,
    }


def normalize_whatsapp(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("55") and len(digits) == 13:
        digits = digits[2:]
    if not re.fullmatch(r"\d{11}", digits):
        return ""
    ddd = int(digits[:2])
    if ddd < 11 or ddd > 99:
        return ""
    if digits[2] != "9":
        return ""
    if is_fake_phone(digits):
        return ""
    return digits


def is_fake_phone(digits: str) -> bool:
    if re.fullmatch(r"(\d)\1{10}", digits):
        return True
    local = digits[2:]
    if re.fullmatch(r"(\d)\1{8}", local):
        return True
    return is_sequential_ascending(local) or is_sequential_descending(local)


def is_sequential_ascending(text: str) -> bool:
    for idx in range(1, len(text)):
        if int(text[idx]) != (int(text[idx - 1]) + 1) % 10:
            return False
    return True


def is_sequential_descending(text: str) -> bool:
    for idx in range(1, len(text)):
        if int(text[idx]) != (int(text[idx - 1]) + 9) % 10:
            return False
    return True


def get_client_ip(handler: BaseHTTPRequestHandler) -> str:
    forwarded = handler.headers.get("X-Forwarded-For", "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    if handler.client_address and handler.client_address[0]:
        return handler.client_address[0]
    return "unknown"


def enforce_lead_rate_limit(ip_address: str) -> None:
    now = time.time()
    recent = [ts for ts in LEAD_RATE_STATE.get(ip_address, []) if now - ts <= LEAD_RATE_WINDOW_SECONDS]
    if len(recent) >= LEAD_RATE_MAX_PER_WINDOW:
        raise ValueError("Muitas tentativas. Aguarde alguns minutos e tente novamente.")
    recent.append(now)
    LEAD_RATE_STATE[ip_address] = recent


def enforce_lead_frequency(ip_address: str, phone: str) -> None:
    now = time.time()
    key = f"{ip_address}:{phone}"
    last = LEAD_LAST_SUBMISSION_BY_KEY.get(key)
    if last and (now - last) < LEAD_MIN_INTERVAL_SECONDS:
        raise ValueError("Envio muito rápido. Aguarde alguns segundos e tente novamente.")
    LEAD_LAST_SUBMISSION_BY_KEY[key] = now


def register_security_block(ip_address: str, reason: str) -> None:
    now = time.time()
    recent = [ts for ts in LEAD_BLOCK_EVENTS_BY_IP.get(ip_address, []) if now - ts <= SECURITY_ALERT_WINDOW_SECONDS]
    recent.append(now)
    LEAD_BLOCK_EVENTS_BY_IP[ip_address] = recent
    print(f"[SECURITY][BLOCK] ip={ip_address} reason={reason} blocks_window={len(recent)}")
    if len(recent) >= SECURITY_ALERT_BLOCK_THRESHOLD:
        print(
            f"[SECURITY][ALERT] Alta taxa de bloqueios para ip={ip_address} "
            f"em {SECURITY_ALERT_WINDOW_SECONDS//60}min: {len(recent)} tentativas bloqueadas."
        )


def verify_turnstile_token(token: str, ip_address: str) -> bool:
    if not TURNSTILE_SECRET_KEY:
        return True
    token = (token or "").strip()
    if not token:
        return False
    payload = (
        f"secret={quote(TURNSTILE_SECRET_KEY)}&response={quote(token)}&remoteip={quote(ip_address)}"
    ).encode("utf-8")
    request = Request(
        "https://challenges.cloudflare.com/turnstile/v0/siteverify",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
            return bool(data.get("success"))
    except Exception:
        return False


def inside(child: Path, parent: Path) -> bool:
    child = child.resolve()
    parent = parent.resolve()
    return child == parent or parent in child.parents


def read_text_file(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8-sig", errors="ignore").strip()
    except OSError:
        return default


def read_score(folder: Path) -> str:
    text = read_text_file(folder / "score-viral.txt")
    if not text:
        return ""
    for line in text.splitlines():
        if line.lower().startswith("score="):
            return line.split("=", 1)[1].strip()
    return ""


def read_quality(folder: Path) -> dict:
    text = read_text_file(folder / "qualidade.json")
    if not text:
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def read_publication(folder: Path) -> str:
    return read_text_file(folder / "publicacao.txt")


def safe_output_path(path_text: str) -> Path | None:
    if not path_text:
        return None
    try:
        path = Path(unquote(path_text)).resolve()
    except OSError:
        return None
    if not inside(path, OUTPUTS):
        return None
    if not path.exists() or not path.is_file():
        return None
    return path


def ready_cut_item(video: Path) -> dict:
    folder = video.parent
    quality = read_quality(folder)
    publication = read_publication(folder)
    score = read_score(folder)
    if not score and quality.get("score") != "":
        score = f"{quality.get('score')}/100"
    stat = video.stat()
    title = folder.name
    if publication:
        title = publication.splitlines()[0].strip() or title
    return {
        "id": quote(str(video), safe=""),
        "title": title.replace("-", " "),
        "file": video.name,
        "folder": str(folder),
        "video": str(video),
        "video_url": f"/v1/arquivo?path={quote(str(video), safe='')}",
        "publication": publication,
        "score": score,
        "quality_status": quality.get("status") or "",
        "quality_score": quality.get("score") or "",
        "duration": quality.get("duration") or "",
        "width": quality.get("width") or "",
        "height": quality.get("height") or "",
        "size_mb": round(stat.st_size / 1024 / 1024, 1),
        "modified_at": stat.st_mtime,
    }


def read_ready_cuts(limit: int = 24, base: Path | None = None) -> list[dict]:
    root = base or OUTPUTS
    if not root.exists() or not inside(root, OUTPUTS):
        return []
    videos: list[Path] = []
    for video in root.glob("**/*.mp4"):
        parts = set(video.parts)
        if parts.intersection(SKIP_OUTPUT_PARTS):
            continue
        if video.name.lower().startswith("source"):
            continue
        videos.append(video)
    videos.sort(
        key=lambda item: (
            "_postar_agora" in item.parts,
            item.stat().st_mtime,
        ),
        reverse=True,
    )
    seen: set[str] = set()
    items: list[dict] = []
    for video in videos:
        key = str(video.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(ready_cut_item(video))
        if len(items) >= limit:
            break
    return items


def enrich_process(process: dict) -> dict:
    result = process.get("result") or {}
    pack = safe_output_path(result.get("posting_pack", ""))
    pack_folder = pack if pack and pack.is_dir() else None
    if not pack_folder:
        raw_pack = str(result.get("posting_pack") or "").strip()
        try:
            candidate_folder = Path(raw_pack).resolve() if raw_pack else None
        except OSError:
            candidate_folder = None
        if candidate_folder and candidate_folder.exists() and candidate_folder.is_dir() and inside(candidate_folder, OUTPUTS):
            pack_folder = candidate_folder
    if pack_folder:
        process["ready_cuts"] = read_ready_cuts(20, pack_folder)
    else:
        process["ready_cuts"] = []
    return process


class Handler(BaseHTTPRequestHandler):
    server_version = "UardonCRM/0.1"

    def log_message(self, format: str, *args) -> None:
        return

    def origin(self) -> str:
        return (self.headers.get("Origin") or "").strip().rstrip("/")

    def cors_origin(self) -> str:
        origin = self.origin()
        return origin if origin in ALLOWED_ORIGINS else ""

    def add_common_security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()")
        self.send_header("Cross-Origin-Resource-Policy", "same-site")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")

    def add_cors_headers(self) -> bool:
        allowed_origin = self.cors_origin()
        if not allowed_origin:
            return False
        self.send_header("Access-Control-Allow-Origin", allowed_origin)
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-User-Id")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        return True

    def send_json(self, data: dict | list, status: int = 200) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.add_common_security_headers()
        self.add_cors_headers()
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_file(self, path: Path) -> None:
        resolved = path.resolve()
        root = MOBILE_WEB.resolve()
        if root not in resolved.parents and resolved != root:
            self.send_json({"error": "Arquivo inválido"}, 403)
            return
        if not resolved.exists() or not resolved.is_file():
            self.send_json({"error": "Arquivo nao encontrado"}, 404)
            return
        raw = resolved.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(resolved.suffix.lower(), "application/octet-stream"))
        self.add_common_security_headers()
        self.add_cors_headers()
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; script-src 'self' 'unsafe-inline' https://challenges.cloudflare.com; "
            "frame-src https://challenges.cloudflare.com; connect-src 'self' https://challenges.cloudflare.com; frame-ancestors 'none';",
        )
        self.send_header("Cache-Control", "public, max-age=300")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_output_file(self, path: Path) -> None:
        resolved = path.resolve()
        if not inside(resolved, OUTPUTS):
            self.send_json({"error": "Arquivo inválido"}, 403)
            return
        if resolved.suffix.lower() not in {".mp4", ".txt", ".json"}:
            self.send_json({"error": "Tipo de arquivo bloqueado"}, 403)
            return
        if not resolved.exists() or not resolved.is_file():
            self.send_json({"error": "Arquivo nao encontrado"}, 404)
            return

        file_size = resolved.stat().st_size
        content_type = CONTENT_TYPES.get(resolved.suffix.lower(), "application/octet-stream")
        range_header = self.headers.get("Range", "")
        if resolved.suffix.lower() == ".mp4" and range_header.startswith("bytes="):
            match = re.match(r"bytes=(\d+)-(\d*)", range_header)
            if match:
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else file_size - 1
                end = min(end, file_size - 1)
                if start <= end:
                    chunk_size = end - start + 1
                    self.send_response(206)
                    self.send_header("Content-Type", content_type)
                    self.add_common_security_headers()
                    self.add_cors_headers()
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                    self.send_header("Content-Length", str(chunk_size))
                    self.end_headers()
                    with resolved.open("rb") as handle:
                        handle.seek(start)
                        self.wfile.write(handle.read(chunk_size))
                    return

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.add_common_security_headers()
        self.add_cors_headers()
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(file_size))
        self.end_headers()
        with resolved.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_JSON_BODY_BYTES:
            raise ValueError("Requisição muito grande.")
        raw = self.rfile.read(length).decode("utf-8")
        parsed = json.loads(raw or "{}")
        if not isinstance(parsed, dict):
            raise ValueError("JSON inválido.")
        return parsed

    def user_id(self) -> str:
        return self.headers.get("X-User-Id") or DEFAULT_USER_ID

    def do_OPTIONS(self) -> None:
        if not self.cors_origin():
            self.send_response(403)
            self.add_common_security_headers()
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(204)
        self.add_common_security_headers()
        self.add_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/app"}:
            self.send_file(MOBILE_WEB / "index.html")
            return
        if parsed.path.startswith("/mobile/"):
            relative = parsed.path.removeprefix("/mobile/").strip("/")
            self.send_file(MOBILE_WEB / relative)
            return
        if parsed.path == "/health":
            self.send_json({"ok": True, "service": "uardon-crm-api"})
            return
        if parsed.path == "/v1/cortes-prontos":
            params = parse_qs(parsed.query)
            limit = int(params.get("limit", ["24"])[0] or 24)
            self.send_json({"items": read_ready_cuts(max(1, min(60, limit)))})
            return
        if parsed.path == "/v1/arquivo":
            params = parse_qs(parsed.query)
            path = safe_output_path(params.get("path", [""])[0])
            if not path:
                self.send_json({"error": "Arquivo inválido"}, 404)
                return
            self.send_output_file(path)
            return
        if parsed.path in {"/v1/jobs", "/v1/cortes"}:
            params = parse_qs(parsed.query)
            limit = int(params.get("limit", ["30"])[0] or 30)
            self.send_json([enrich_process(item) for item in list_jobs(self.user_id(), max(1, min(100, limit)))])
            return
        if parsed.path == "/v1/leads":
            params = parse_qs(parsed.query)
            limit = int(params.get("limit", ["50"])[0] or 50)
            self.send_json(list_leads(self.user_id(), max(1, min(200, limit))))
            return
        match = re.match(r"^/v1/(?:jobs|cortes)/([^/]+)$", parsed.path)
        if match:
            job = get_job(match.group(1), self.user_id())
            if not job:
                self.send_json({"error": "Processamento nao encontrado"}, 404)
                return
            self.send_json(enrich_process(job))
            return
        self.send_json({"error": "Rota nao encontrada"}, 404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        client_ip = get_client_ip(self)
        cancel_match = re.match(r"^/v1/(?:jobs|cortes)/([^/]+)/cancelar$", parsed.path)
        if cancel_match:
            job = get_job(cancel_match.group(1), self.user_id())
            if not job:
                self.send_json({"error": "Processamento nao encontrado"}, 404)
                return
            cancelled = cancel_job(job["id"])
            updated = get_job(job["id"], self.user_id()) or job
            self.send_json({"cancelled": cancelled, "process": enrich_process(updated)})
            return
        if parsed.path not in {"/v1/jobs", "/v1/cortes"}:
            if parsed.path != "/v1/leads":
                self.send_json({"error": "Rota nao encontrada"}, 404)
                return
        try:
            payload = self.read_json()
            if parsed.path == "/v1/leads":
                enforce_lead_rate_limit(client_ip)
                lead_data = normalize_lead_request(payload)
                enforce_lead_frequency(client_ip, lead_data["phone"])
                turnstile_token = str(payload.get("turnstile_token") or payload.get("cf_turnstile_token") or "").strip()
                if not verify_turnstile_token(turnstile_token, client_ip):
                    register_security_block(client_ip, "turnstile_failed")
                    raise ValueError("Verificação de segurança não concluída. Atualize a página e tente novamente.")
                lead = create_lead(str(uuid4()), self.user_id(), **lead_data)
                self.send_json(lead, 201)
                return
            request = normalize_request(payload)
            job = create_job(str(uuid4()), self.user_id(), request["url"], request)
            enqueue_job(job["id"])
            self.send_json(job, 201)
        except ValueError as exc:
            register_security_block(client_ip, str(exc))
            self.send_json({"error": str(exc)}, 400)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 500)


def main() -> None:
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Uardon CRM API: http://127.0.0.1:{PORT}")
    print(f"Health: http://127.0.0.1:{PORT}/health")
    server.serve_forever()


if __name__ == "__main__":
    main()
