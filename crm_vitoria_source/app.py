import csv
import calendar
import hashlib
import hmac
import json
import os
import re
import shutil
import sys
import time
import unicodedata
import urllib.parse
import urllib.error
import urllib.request
import uuid
from copy import deepcopy
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path

try:
    import psycopg
except Exception:
    psycopg = None

from flask import (
    Flask,
    Response,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)


BASE_DIR = Path(__file__).resolve().parent
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR))
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else BASE_DIR
DEFAULT_STORAGE_BASE = Path("/data") if (os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("RENDER")) else APP_DIR
DATA_FILE = Path(os.environ.get("CRM_DATA_FILE", str(DEFAULT_STORAGE_BASE / "data.json")))
UPLOAD_DIR = Path(os.environ.get("CRM_UPLOAD_DIR", str(DEFAULT_STORAGE_BASE / "uploads")))
SEED_DATA_FILE = BASE_DIR / "data.json"
DATABASE_URL = (os.environ.get("DATABASE_URL") or "").strip()
WRITE_LOCK_KEY = 761451

# Em produção com volume novo, restaura o snapshot local para não iniciar zerado.
if not DATA_FILE.exists() and SEED_DATA_FILE.exists():
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SEED_DATA_FILE, DATA_FILE)

DEFAULT_DATA = {
    "users": [
        {
            "id": 1,
            "username": "vitoria",
            "email": "",
            "password": "123456",
            "name": "Vitória Uardon",
        }
    ],
    "config": {"nomeArquiteta": "Vitória Uardon", "estudio": "Studio Arq. & Int."},
    "leads": [],
    "clientes": [],
    "projetos": [],
    "tarefas": [],
    "eventos": [],
    "despesas": [],
    "feedbacks": [],
    "dismissed_notifications": [],
    "audit_logs": [],
}

PROJECT_STAGES = [
    "Briefing e medição",
    "Reunião de layout",
    "Apresentação do 3D",
    "Detalhamento de marcenaria",
    "Entrega do caderno final",
]

TASK_TYPES = ["Follow-up", "Cobrança", "Projeto", "Comercial", "Interno"]
EVENT_TYPES = ["Reunião", "Medição", "Apresentação", "Follow-up", "Cobrança", "Outro"]
MEETING_TYPES = ["Presencial", "Google Meet", "Teams", "Zoom", "Outro"]
EXPENSE_CATEGORIES = ["Fixo", "Software", "Equipe", "Marketing", "Fornecedor", "Imposto", "Escritório", "Outro"]
GOOGLE_CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
LEAD_LOSS_REASONS = [
    "Orçamento acima do previsto",
    "Cliente sem retorno",
    "Prazo incompatível",
    "Escopo não aderente",
    "Fechou com outro profissional",
    "Projeto adiado",
    "Outro",
]

app = Flask(
    __name__,
    template_folder=str(RESOURCE_DIR / "templates"),
    static_folder=str(RESOURCE_DIR / "static"),
)
CRM_ENV = (os.environ.get("CRM_ENV") or "development").strip().lower()
CRM_SECRET = os.environ.get("CRM_SECRET_KEY")
if CRM_ENV == "production" and not CRM_SECRET:
    raise RuntimeError("CRM_SECRET_KEY não configurada para produção.")
app.secret_key = CRM_SECRET or "crm-vitoria-local-dev-only"

PUBLIC_LEAD_RATE_LIMIT = {}
PUBLIC_LEAD_CONTACT_RATE_LIMIT = {}
PUBLIC_LEAD_ALLOWED_ORIGINS = {
    "https://uardon.com.br",
    "https://www.uardon.com.br",
}
LEAD_OWNER_DEFAULT = "Vitória Uardon"
LEAD_FIRST_CONTACT_SLA_MINUTES = 15


def fix_mojibake_text(value):
    if not isinstance(value, str):
        return value
    if "" not in value and "" not in value and "" not in value:
        return value
    try:
        fixed = value.encode("latin-1").decode("utf-8")
        return fixed if fixed else value
    except Exception:
        return value


def normalize_text_payload(value):
    if isinstance(value, dict):
        return {k: normalize_text_payload(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize_text_payload(v) for v in value]
    return fix_mojibake_text(value)


def ensure_data_file():
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    if not DATA_FILE.exists():
        save_data(deepcopy(DEFAULT_DATA))


def db_enabled():
    return bool(DATABASE_URL and psycopg is not None)


def db_connect():
    if not db_enabled():
        return None
    return psycopg.connect(DATABASE_URL)


def ensure_db_schema(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS crm_state (
                id SMALLINT PRIMARY KEY,
                payload JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    conn.commit()


def db_load_data():
    conn = db_connect()
    if conn is None:
        return None
    try:
        ensure_db_schema(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT payload FROM crm_state WHERE id = 1")
            row = cur.fetchone()
        if row and row[0]:
            return row[0]
        return None
    finally:
        conn.close()


def db_save_data(data):
    conn = db_connect()
    if conn is None:
        return False
    try:
        ensure_db_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO crm_state (id, payload, updated_at)
                VALUES (1, %s::jsonb, NOW())
                ON CONFLICT (id)
                DO UPDATE SET payload = EXCLUDED.payload, updated_at = NOW()
                """,
                (json.dumps(data, ensure_ascii=False),),
            )
        conn.commit()
        return True
    finally:
        conn.close()


def acquire_write_lock():
    if not db_enabled():
        return
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return
    if request.method == "OPTIONS":
        return
    lock_conn = db_connect()
    if lock_conn is None:
        return
    try:
        with lock_conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(%s)", (WRITE_LOCK_KEY,))
        g.crm_write_lock_conn = lock_conn
    except Exception:
        lock_conn.close()
        raise


def release_write_lock(_exc=None):
    lock_conn = getattr(g, "crm_write_lock_conn", None)
    if not lock_conn:
        return
    try:
        with lock_conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (WRITE_LOCK_KEY,))
    finally:
        lock_conn.close()
        g.crm_write_lock_conn = None


app.before_request(acquire_write_lock)
app.teardown_request(release_write_lock)


def load_data_from_file():
    ensure_data_file()
    try:
        raw = DATA_FILE.read_text(encoding="utf-8-sig")
        data = json.loads(raw) if raw.strip() else deepcopy(DEFAULT_DATA)
    except json.JSONDecodeError:
        backup = DATA_FILE.with_suffix(f".invalid_{datetime.now():%Y%m%d_%H%M%S}.json")
        DATA_FILE.replace(backup)
        data = deepcopy(DEFAULT_DATA)
    for key, value in DEFAULT_DATA.items():
        data.setdefault(key, deepcopy(value))
    for user in data.get("users", []):
        user.setdefault("email", "")
    data.setdefault("dismissed_notifications", [])
    return normalize_text_payload(data)


def load_data():
    if db_enabled():
        try:
            db_data = db_load_data()
            if db_data is not None:
                data = db_data
            else:
                data = load_data_from_file()
                db_save_data(data)
        except Exception:
            data = load_data_from_file()
    else:
        data = load_data_from_file()
    for key, value in DEFAULT_DATA.items():
        data.setdefault(key, deepcopy(value))
    for user in data.get("users", []):
        user.setdefault("email", "")
    data.setdefault("dismissed_notifications", [])
    return normalize_text_payload(data)


def save_data(data):
    if db_enabled():
        try:
            if db_save_data(data):
                return
        except Exception:
            pass
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def next_id(items):
    return max([int(item.get("id", 0) or 0) for item in items] + [0]) + 1


def today_br():
    return date.today().strftime("%d/%m/%Y")


def parse_date(value):
    if not value:
        return None
    value = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None


def format_date_br(value):
    parsed = parse_date(value)
    return parsed.strftime("%d/%m/%Y") if parsed else (value or "")


def money_to_float(value):
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = re.sub(r"[^\d,.-]", "", str(value)).strip()
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return 0.0


def phone_digits(value):
    digits = re.sub(r"\D", "", value or "")
    if digits and not digits.startswith("55"):
        digits = "55" + digits
    return digits


def whatsapp_link(phone, message=""):
    digits = phone_digits(phone)
    text = urllib.parse.quote_plus(message or "")
    return f"https://web.whatsapp.com/send?phone={digits}&text={text}" if digits else "#"


def public_lead_origin():
    allowed = set(PUBLIC_LEAD_ALLOWED_ORIGINS)
    extra = os.environ.get("CRM_ALLOWED_ORIGINS", "")
    allowed.update(origin.strip().rstrip("/") for origin in extra.split(",") if origin.strip())
    origin = (request.headers.get("Origin") or "").rstrip("/")
    if origin in allowed:
        return origin
    if origin.startswith("http://localhost:") or origin.startswith("http://127.0.0.1:"):
        return origin
    return ""


def public_lead_response(payload=None, status=200):
    response = Response(
        json.dumps(payload or {}, ensure_ascii=False),
        status=status,
        mimetype="application/json",
    )
    origin = public_lead_origin()
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
    response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-User-Id, X-Uardon-Timestamp, X-Uardon-Signature, Idempotency-Key"
    response.headers["Access-Control-Max-Age"] = "86400"
    return response


def public_lead_error(message, status=400, code="invalid_request"):
    return public_lead_response({"ok": False, "error": message, "code": code}, status)


def public_lead_client_ip():
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def public_lead_rate_limited(ip, limit=5, window_seconds=600):
    now = datetime.now()
    cutoff = now - timedelta(seconds=window_seconds)
    attempts = [item for item in PUBLIC_LEAD_RATE_LIMIT.get(ip, []) if item > cutoff]
    if len(attempts) >= limit:
        PUBLIC_LEAD_RATE_LIMIT[ip] = attempts
        return True
    attempts.append(now)
    PUBLIC_LEAD_RATE_LIMIT[ip] = attempts
    return False



def public_lead_contact_rate_limited(contact_key, limit=3, window_seconds=3600):
    if not contact_key:
        return False
    now = datetime.now()
    cutoff = now - timedelta(seconds=window_seconds)
    attempts = [item for item in PUBLIC_LEAD_CONTACT_RATE_LIMIT.get(contact_key, []) if item > cutoff]
    if len(attempts) >= limit:
        PUBLIC_LEAD_CONTACT_RATE_LIMIT[contact_key] = attempts
        return True
    attempts.append(now)
    PUBLIC_LEAD_CONTACT_RATE_LIMIT[contact_key] = attempts
    return False


def public_lead_hmac_secret():
    return (os.environ.get("PUBLIC_LEAD_HMAC_SECRET") or os.environ.get("CRM_PUBLIC_LEAD_HMAC_SECRET") or "").strip()


def verify_public_lead_signature(raw_body):
    secret = public_lead_hmac_secret()
    if not secret:
        return True, ""
    timestamp = (request.headers.get("X-Uardon-Timestamp") or "").strip()
    signature = (request.headers.get("X-Uardon-Signature") or "").strip()
    if not timestamp or not signature:
        return False, "Assinatura de envio ausente."
    try:
        sent_at = int(timestamp)
    except ValueError:
        return False, "Assinatura de envio inválida."
    if abs(int(time.time()) - sent_at) > 300:
        return False, "Envio expirado. Atualize a página e tente novamente."
    signed_payload = timestamp.encode("utf-8") + b"." + (raw_body or b"")
    expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    provided = signature[7:] if signature.startswith("sha256=") else signature
    if not hmac.compare_digest(expected, provided):
        return False, "Assinatura de envio inválida."
    return True, ""


def clean_public_text(value, max_length=300):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:max_length]


def public_lead_fingerprint(phone, project_type, name):
    base = f"{normalize_brazil_phone(phone)}|{clean_public_text(project_type, 80).lower()}|{clean_public_text(name, 120).lower()}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def find_recent_public_lead(data, fingerprint, hours=24):
    cutoff = datetime.now() - timedelta(hours=hours)
    for lead in reversed(data.get("leads", [])):
        if lead.get("idempotency_key") != fingerprint and lead.get("public_fingerprint") != fingerprint:
            continue
        created_raw = lead.get("created_at") or ""
        try:
            created_at = datetime.fromisoformat(created_raw)
        except ValueError:
            return lead
        if created_at >= cutoff:
            return lead
    return None


def audit_public_lead(data, event, status="ok", lead=None, code="", details=None):
    entry = {
        "id": str(uuid.uuid4()),
        "event": event,
        "status": status,
        "code": code,
        "lead_id": lead.get("id") if isinstance(lead, dict) else None,
        "ip": public_lead_client_ip(),
        "origin": (request.headers.get("Origin") or "").strip(),
        "user_agent": (request.headers.get("User-Agent") or "")[:220],
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "details": details or {},
    }
    logs = data.setdefault("audit_logs", [])
    logs.append(entry)
    del logs[:-500]

def normalize_brazil_phone(value):
    digits = re.sub(r"\D", "", str(value or ""))
    if digits.startswith("55") and len(digits) == 13:
        digits = digits[2:]
    return digits


def is_sequential_phone(value, direction=1):
    for index in range(1, len(value)):
        expected = (int(value[index - 1]) + direction) % 10
        if int(value[index]) != expected:
            return False
    return True


def is_valid_brazil_whatsapp(value):
    digits = normalize_brazil_phone(value)
    if not re.fullmatch(r"\d{11}", digits):
        return False
    ddd = int(digits[:2])
    if ddd < 11 or ddd > 99:
        return False
    if digits[2] != "9":
        return False
    local = digits[2:]
    if re.fullmatch(r"(\d)\1+", digits) or re.fullmatch(r"(\d)\1+", local):
        return False
    if is_sequential_phone(local, 1) or is_sequential_phone(local, -1):
        return False
    return True


def turnstile_secret():
    for key in ("TURNSTILE_SECRET_KEY", "CLOUDFLARE_TURNSTILE_SECRET", "CHAVE_SECRETA_DA_CATRACA"):
        value = (os.environ.get(key) or "").strip()
        if value:
            return value
    return ""

def turnstile_fail_open_enabled():
    raw = (os.environ.get("TURNSTILE_FAIL_OPEN") or "").strip().lower()
    if not raw:
        return True
    return raw in ("1", "true", "yes", "on")


def verify_turnstile_token(token, remote_ip=""):
    secret = turnstile_secret()
    if not secret:
        return True, "", ""
    if not token:
        return False, "Confirmao de segurana pendente.", "missing-input-response"
    # Do not send remoteip here: requests pass through Cloudflare and Railway,
    # and proxy IP mismatches can make otherwise valid Turnstile tokens fail.
    payload = {"secret": secret, "response": token}
    encoded = urllib.parse.urlencode(payload).encode("utf-8")
    try:
        req = urllib.request.Request(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data=encoded,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as result:
            parsed = json.loads(result.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False, "Não foi possível validar a segurança agora. Tente novamente em alguns instantes.", "siteverify_unavailable"
    if not parsed.get("success"):
        errors = parsed.get("error-codes") or []
        error_code = ",".join(str(item) for item in errors) if errors else "invalid"
        return False, "Confirmao de segurana invlida. Atualize a pgina e tente novamente.", error_code
    return True, "", ""



def google_calendar_url(title, start_date, start_time="", end_time="", details="", location=""):
    day = parse_date(start_date) or date.today()
    start_time = start_time or "09:00"
    end_time = end_time or ""
    try:
        start_dt = datetime.combine(day, datetime.strptime(start_time, "%H:%M").time())
    except ValueError:
        start_dt = datetime.combine(day, datetime.strptime("09:00", "%H:%M").time())
    if end_time:
        try:
            end_dt = datetime.combine(day, datetime.strptime(end_time, "%H:%M").time())
        except ValueError:
            end_dt = start_dt + timedelta(hours=1)
    else:
        end_dt = start_dt + timedelta(hours=1)
    params = {
        "action": "TEMPLATE",
        "text": title,
        "dates": f"{start_dt:%Y%m%dT%H%M%S}/{end_dt:%Y%m%dT%H%M%S}",
        "details": details,
        "location": location,
    }
    return "https://calendar.google.com/calendar/render?" + urllib.parse.urlencode(params)


def google_calendar_paths():
    return {
        "credentials": APP_DIR / "google_credentials.json",
        "token": APP_DIR / "google_token.json",
    }


def google_calendar_status():
    paths = google_calendar_paths()
    deps_ok = True
    try:
        import googleapiclient  # noqa: F401
        import google_auth_oauthlib  # noqa: F401
    except Exception:
        deps_ok = False
    return {
        "deps_ok": deps_ok,
        "credentials_exists": paths["credentials"].exists(),
        "connected": paths["token"].exists(),
        "credentials_path": str(paths["credentials"]),
        "token_path": str(paths["token"]),
        "ready": deps_ok and paths["credentials"].exists() and paths["token"].exists(),
    }


def google_calendar_service(force_auth=False):
    paths = google_calendar_paths()
    if not paths["credentials"].exists():
        raise RuntimeError("Arquivo google_credentials.json não encontrado na pasta do CRM.")
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except Exception as exc:
        raise RuntimeError("Dependências do Google Calendar não instaladas.") from exc

    creds = None
    if paths["token"].exists():
        creds = Credentials.from_authorized_user_file(str(paths["token"]), GOOGLE_CALENDAR_SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if force_auth or not creds or not creds.valid:
        raise RuntimeError("Google Agenda ainda não foi autorizado. Clique em Conectar na Agenda.")
    paths["token"].write_text(creds.to_json(), encoding="utf-8")
    return build("calendar", "v3", credentials=creds)


def google_oauth_flow():
    paths = google_calendar_paths()
    if not paths["credentials"].exists():
        raise RuntimeError("Arquivo google_credentials.json não encontrado na pasta do CRM.")
    try:
        from google_auth_oauthlib.flow import Flow
    except Exception as exc:
        raise RuntimeError("Dependências do Google Calendar não instaladas.") from exc
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
    redirect_uri = url_for("google_calendar_callback", _external=True)
    return Flow.from_client_secrets_file(
        str(paths["credentials"]),
        scopes=GOOGLE_CALENDAR_SCOPES,
        redirect_uri=redirect_uri,
    )


def google_event_body(event):
    day = parse_date(event.get("data")) or date.today()
    start_time = event.get("hora") or "09:00"
    end_time = event.get("hora_fim") or ""
    try:
        datetime.strptime(start_time, "%H:%M")
    except ValueError:
        start_time = "09:00"
    if end_time:
        try:
            datetime.strptime(end_time, "%H:%M")
        except ValueError:
            end_time = ""
    if not end_time:
        start_dt = datetime.combine(day, datetime.strptime(start_time, "%H:%M").time())
        end_time = (start_dt + timedelta(hours=1)).strftime("%H:%M")
    details = event.get("observacoes") or ""
    if event.get("cliente"):
        details += f"\nCliente: {event.get('cliente')}"
    if event.get("projeto"):
        details += f"\nProjeto: {event.get('projeto')}"
    if event.get("link"):
        details += f"\nLink: {event.get('link')}"
    body = {
        "summary": event.get("titulo") or "Compromisso",
        "location": event.get("local") or event.get("link") or "",
        "description": details.strip(),
        "start": {"dateTime": f"{day.isoformat()}T{start_time}:00", "timeZone": "America/Sao_Paulo"},
        "end": {"dateTime": f"{day.isoformat()}T{end_time}:00", "timeZone": "America/Sao_Paulo"},
        "reminders": {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": 30}],
        },
    }
    if (event.get("reuniao_tipo") or "").strip().lower() == "google meet" and not event.get("link"):
        request_id = event.get("google_meet_request_id") or f"crm-vitoria-{event.get('id') or uuid.uuid4().hex}"
        event["google_meet_request_id"] = request_id
        body["conferenceData"] = {
            "createRequest": {
                "requestId": request_id,
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        }
    return body


def sync_event_to_google(event):
    service = google_calendar_service()
    body = google_event_body(event)
    if event.get("google_event_id"):
        google_event = service.events().update(calendarId="primary", eventId=event["google_event_id"], body=body, conferenceDataVersion=1).execute()
    else:
        google_event = service.events().insert(calendarId="primary", body=body, conferenceDataVersion=1).execute()
    meet_link = google_event.get("hangoutLink") or ""
    if not meet_link:
        for entry in (google_event.get("conferenceData") or {}).get("entryPoints", []):
            if entry.get("entryPointType") == "video" and entry.get("uri"):
                meet_link = entry.get("uri")
                break
    if meet_link and ((event.get("reuniao_tipo") or "").strip().lower() == "google meet" or not event.get("link")):
        event["link"] = meet_link
        event["reuniao_tipo"] = "Google Meet"
    event["google_event_id"] = google_event.get("id")
    event["google_html_link"] = google_event.get("htmlLink")
    event["google_synced_at"] = datetime.now().isoformat(timespec="seconds")
    event["google_sync_error"] = ""
    return google_event


def google_datetime_parts(value):
    if not value:
        return "", "", ""
    if "T" not in value:
        parsed = parse_date(value)
        return (parsed.isoformat(), "", "") if parsed else ("", "", "")
    cleaned = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return "", "", ""
    return parsed.date().isoformat(), parsed.strftime("%H:%M"), ""


def import_google_events_to_crm(data, days_ahead=90):
    service = google_calendar_service()
    now = datetime.now().isoformat() + "Z"
    until = (datetime.now() + timedelta(days=days_ahead)).isoformat() + "Z"
    response = service.events().list(
        calendarId="primary",
        timeMin=now,
        timeMax=until,
        singleEvents=True,
        orderBy="startTime",
        maxResults=50,
    ).execute()
    google_events = response.get("items", [])
    existing_ids = {str(event.get("google_event_id")) for event in data.get("eventos", []) if event.get("google_event_id")}
    created = 0
    updated = 0
    for google_event in google_events:
        google_id = google_event.get("id")
        if not google_id:
            continue
        start_raw = (google_event.get("start") or {}).get("dateTime") or (google_event.get("start") or {}).get("date")
        end_raw = (google_event.get("end") or {}).get("dateTime") or (google_event.get("end") or {}).get("date")
        event_date, start_time, _ = google_datetime_parts(start_raw)
        _, end_time, _ = google_datetime_parts(end_raw)
        if google_id in existing_ids:
            for event in data.get("eventos", []):
                if str(event.get("google_event_id")) == str(google_id):
                    event["titulo"] = google_event.get("summary") or event.get("titulo") or "Compromisso Google"
                    event["data"] = event_date or event.get("data", "")
                    event["hora"] = start_time or event.get("hora", "")
                    event["hora_fim"] = end_time or event.get("hora_fim", "")
                    event["local"] = google_event.get("location") or event.get("local", "")
                    event["observacoes"] = google_event.get("description") or event.get("observacoes", "")
                    event["google_html_link"] = google_event.get("htmlLink") or event.get("google_html_link", "")
                    event["google_synced_at"] = datetime.now().isoformat(timespec="seconds")
                    updated += 1
                    break
            continue
        event = {
            "id": next_id(data["eventos"]),
            "titulo": google_event.get("summary") or "Compromisso Google",
            "tipo": "Reunião",
            "data": event_date,
            "hora": start_time,
            "hora_fim": end_time,
            "cliente_id": "",
            "cliente": "",
            "projeto_id": "",
            "projeto": "",
            "reuniao_tipo": "Google Meet" if google_event.get("hangoutLink") else "Outro",
            "link": google_event.get("hangoutLink") or "",
            "local": google_event.get("location") or "",
            "observacoes": google_event.get("description") or "",
            "status": "agendado",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "origem": "google_agenda",
            "google_event_id": google_id,
            "google_html_link": google_event.get("htmlLink") or "",
            "google_synced_at": datetime.now().isoformat(timespec="seconds"),
            "google_sync_error": "",
        }
        data["eventos"].append(event)
        existing_ids.add(str(google_id))
        created += 1
    return {"created": created, "updated": updated, "total": len(google_events)}


def normalize_match_text(value):
    normalized = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9]+", " ", normalized.lower())
    return f" {text.strip()} "


def match_tokens(value):
    ignored = {
        "projeto",
        "reuniao",
        "apresentacao",
        "briefing",
        "layout",
        "medicao",
        "agenda",
        "google",
        "meet",
        "zoom",
        "teams",
        "casa",
        "apto",
        "apartamento",
        "area",
        "cliente",
    }
    return [token for token in normalize_match_text(value).split() if len(token) >= 4 and token not in ignored]


def event_match_score(haystack, names):
    score = 0
    matched = []
    for name, weight in names:
        normalized_name = normalize_match_text(name)
        compact_name = normalized_name.strip()
        if not compact_name:
            continue
        if f" {compact_name} " in haystack:
            score += weight * 3
            matched.append(compact_name)
            continue
        tokens = match_tokens(name)
        token_hits = [token for token in tokens if f" {token} " in haystack]
        if token_hits:
            score += weight * len(token_hits)
            matched.extend(token_hits)
    return score, sorted(set(matched))


def event_link_suggestion(event, data):
    if event.get("cliente_id") or event.get("projeto_id"):
        return None
    haystack = normalize_match_text(
        " ".join(
            [
                event.get("titulo", ""),
                event.get("observacoes", ""),
                event.get("local", ""),
                event.get("cliente", ""),
                event.get("projeto", ""),
            ]
        )
    )
    best = None
    for project in data.get("projetos", []):
        linked_client = find_by_id(data.get("clientes", []), project.get("cliente_id"))
        names = [
            (project.get("nome", ""), 4),
            (project.get("cliente", ""), 3),
            (linked_client.get("nome", "") if linked_client else "", 3),
            (project.get("ambiente", ""), 1),
            (project.get("tipo", ""), 1),
        ]
        score, matched = event_match_score(haystack, names)
        if score >= 4 and (not best or score > best["score"]):
            best = {"type": "project", "id": project.get("id"), "label": project.get("nome"), "score": score, "matched": matched}
    for client in data.get("clientes", []):
        names = [
            (client.get("nome", ""), 4),
            (client.get("email", ""), 2),
            (client.get("cidade", ""), 1),
            (client.get("profissao", ""), 1),
        ]
        score, matched = event_match_score(haystack, names)
        if score >= 4 and (not best or score > best["score"]):
            best = {"type": "client", "id": client.get("id"), "label": client.get("nome"), "score": score, "matched": matched}
    if not best:
        return None
    best["confidence"] = "alta" if best["score"] >= 8 else "media"
    best["reason"] = ", ".join(best["matched"][:3])
    return best


def apply_event_link(data, event, client=None, project=None):
    if project:
        event["projeto_id"] = project.get("id")
        event["projeto"] = project.get("nome")
        linked_client = find_by_id(data["clientes"], project.get("cliente_id"))
        if linked_client:
            event["cliente_id"] = linked_client.get("id")
            event["cliente"] = linked_client.get("nome")
        elif client:
            event["cliente_id"] = client.get("id")
            event["cliente"] = client.get("nome")
        else:
            event["cliente_id"] = ""
            event["cliente"] = ""
    elif client:
        event["cliente_id"] = client.get("id")
        event["cliente"] = client.get("nome")
        event["projeto_id"] = ""
        event["projeto"] = ""
    else:
        event["cliente_id"] = ""
        event["cliente"] = ""
        event["projeto_id"] = ""
        event["projeto"] = ""
    event["vinculo_atualizado_em"] = today_br()
    return event


def add_history_entry(target, title, description, origin="sistema", source_key=""):
    if not target:
        return False
    history = target.setdefault("historico", [])
    if source_key and any(item.get("source_key") == source_key for item in history):
        return False
    history.append(
        {
            "data": today_br(),
            "titulo": title,
            "descricao": description,
            "origem": origin,
            "source_key": source_key,
        }
    )
    return True


def register_operation_history(data, title, description, origin="sistema", source_key="", client=None, project=None, lead=None, update_client=True):
    if project:
        add_history_entry(project, title, description, origin, source_key)
        if not client:
            client = find_by_id(data.get("clientes", []), project.get("cliente_id"))
    if client:
        add_history_entry(client, title, description, origin, source_key)
        if update_client:
            client["ultima_interacao"] = today_br()
    if lead:
        add_history_entry(lead, title, description, origin, source_key)


def task_history_targets(data, task):
    project = None
    client = None
    lead = None
    if task.get("vinculo_tipo") == "projeto" and task.get("vinculo_id"):
        project = find_by_id(data.get("projetos", []), task.get("vinculo_id"))
    if task.get("vinculo_tipo") == "cliente" and task.get("vinculo_id"):
        client = find_by_id(data.get("clientes", []), task.get("vinculo_id"))
    if task.get("cliente_id"):
        client = find_by_id(data.get("clientes", []), task.get("cliente_id")) or client
    if project and not client:
        client = find_by_id(data.get("clientes", []), project.get("cliente_id"))
    if task.get("vinculo_tipo") == "lead" and task.get("vinculo_id"):
        lead = find_by_id(data.get("leads", []), task.get("vinculo_id"))
    return client, project, lead


def register_completed_event_history(data, event):
    history_key = f"agenda:{event.get('id')}"
    title = event.get("titulo") or "Compromisso"
    event_date = format_date_br(event.get("data")) or today_br()
    event_time = event.get("hora") or "sem horário"
    description = f"Compromisso concluído pela Agenda: {title} em {event_date} às {event_time}."
    if event.get("observacoes"):
        description += f" Observações: {event.get('observacoes')}"
    project = find_by_id(data.get("projetos", []), event.get("projeto_id"))
    client = find_by_id(data.get("clientes", []), event.get("cliente_id"))
    register_operation_history(data, f"Agenda: {title}", description, "agenda", history_key, client=client, project=project)
    event["historico_registrado_em"] = today_br()


def event_next_action_rule(event):
    if not (event.get("projeto_id") or event.get("cliente_id")):
        return None
    text = normalize_match_text(
        " ".join(
            [
                event.get("titulo", ""),
                event.get("tipo", ""),
                event.get("reuniao_tipo", ""),
                event.get("observacoes", ""),
            ]
        )
    )
    rules = [
        (("briefing", "medicao"), "Registrar decisões do briefing", "Consolidar decisões, pendências e próximo passo do briefing.", "Projeto", "Média"),
        (("3d", "apresentacao"), "Consolidar ajustes da apresentação", "Registrar ajustes solicitados e atualizar o próximo passo do projeto.", "Projeto", "Média"),
        (("layout",), "Registrar ajustes de layout", "Organizar ajustes combinados e definir o próximo passo do projeto.", "Projeto", "Média"),
        (("proposta", "orcamento"), "Fazer follow-up da proposta", "Chamar o cliente, confirmar dúvidas e conduzir a decisão.", "Comercial", "Alta"),
        (("reuniao", "meet", "teams", "zoom"), "Registrar decisões da reunião", "Anotar decisões, pendências e próximo passo combinado.", "Projeto", "Média"),
    ]
    for keywords, title, description, task_type, priority in rules:
        if any(f" {keyword} " in text for keyword in keywords):
            return {"titulo": title, "descricao": description, "tipo": task_type, "pri": priority}
    return None


def has_automation_task(data, automation_key):
    return any(task.get("automation_key") == automation_key for task in data.get("tarefas", []))


def create_event_next_action_task(data, event):
    rule = event_next_action_rule(event)
    if not rule:
        return None
    key = f"event_next_action:{event.get('id')}"
    if has_automation_task(data, key):
        return None
    project = find_by_id(data.get("projetos", []), event.get("projeto_id"))
    client = find_by_id(data.get("clientes", []), event.get("cliente_id"))
    if project and not client:
        client = find_by_id(data.get("clientes", []), project.get("cliente_id"))
    vinculo_tipo = "projeto" if project else "cliente"
    vinculo_id = project.get("id") if project else client.get("id") if client else ""
    vinculo_nome = project.get("nome") if project else client.get("nome") if client else event.get("titulo")
    task = {
        "id": next_id(data["tarefas"]),
        "titulo": rule["titulo"],
        "text": rule["titulo"],
        "descricao": f"{rule['descricao']} Origem: compromisso '{event.get('titulo') or 'Agenda'}'.",
        "tipo": rule["tipo"],
        "pri": rule["pri"],
        "prazo": (date.today() + timedelta(days=1)).isoformat(),
        "done": False,
        "status": "Pendente",
        "responsavel": "Vitória Uardon",
        "vinculo_tipo": vinculo_tipo,
        "vinculo_id": vinculo_id,
        "vinculo_nome": vinculo_nome,
        "cliente_id": client.get("id") if client else "",
        "origem": "automacao",
        "automation_key": key,
        "source_event_id": event.get("id"),
        "done_at": "",
    }
    data["tarefas"].append(task)
    event["next_action_task_id"] = task["id"]
    return task


def create_manual_event_action_task(data, event, title, task_type, priority, due_date, description):
    project = find_by_id(data.get("projetos", []), event.get("projeto_id"))
    client = find_by_id(data.get("clientes", []), event.get("cliente_id"))
    if project and not client:
        client = find_by_id(data.get("clientes", []), project.get("cliente_id"))
    vinculo_tipo = "projeto" if project else "cliente" if client else "agenda"
    vinculo_id = project.get("id") if project else client.get("id") if client else event.get("id")
    vinculo_nome = project.get("nome") if project else client.get("nome") if client else event.get("titulo")
    task = {
        "id": next_id(data["tarefas"]),
        "titulo": title,
        "text": title,
        "descricao": f"{description or 'Próxima ação criada a partir da Agenda.'} Origem: compromisso '{event.get('titulo') or 'Agenda'}'.",
        "tipo": task_type or "Projeto",
        "pri": priority or "Média",
        "prazo": due_date or (date.today() + timedelta(days=1)).isoformat(),
        "done": False,
        "status": "Pendente",
        "responsavel": "Vitória Uardon",
        "vinculo_tipo": vinculo_tipo,
        "vinculo_id": vinculo_id,
        "vinculo_nome": vinculo_nome,
        "cliente_id": client.get("id") if client else "",
        "origem": "agenda",
        "source_event_id": event.get("id"),
        "done_at": "",
    }
    data["tarefas"].append(task)
    event.setdefault("manual_action_task_ids", []).append(task["id"])
    event["last_action_task_id"] = task["id"]
    entry = {
        "data": today_br(),
        "titulo": "Próxima ação criada",
        "descricao": f"{title} - {task.get('prazo') or 'sem prazo definido'}",
        "source_key": f"event_manual_action:{event.get('id')}:{task['id']}",
    }
    if project:
        project.setdefault("historico", []).append(dict(entry))
    if client:
        client.setdefault("historico", []).append(dict(entry))
        client["ultima_interacao"] = today_br()
    register_operation_history(
        data,
        "Próxima ação criada",
        f"{title} - {task.get('prazo') or 'sem prazo definido'}",
        "agenda",
        f"event_manual_action:{event.get('id')}:{task['id']}",
        client=client,
        project=project,
    )
    return task


def mailto_link(email, subject="", body=""):
    if not email:
        return "#"
    return "mailto:" + email + "?" + urllib.parse.urlencode({"subject": subject, "body": body})


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)

    return wrapper


def current_brand(data):
    config = data.get("config", {})
    return config.get("estudio") or "Studio Arq. & Int."


def nav_counts(data):
    return {
        "clientes": len(data.get("clientes", [])),
        "projetos": len(data.get("projetos", [])),
        "propostas": len([l for l in data.get("leads", []) if (l.get("status") or "novo").lower() not in ("perdido", "convertido")]),
    }


def open_tasks_count(data):
    return len([task for task in data.get("tarefas", []) if not task.get("done")])


def task_context(task, data):
    if task.get("cliente_id"):
        client = find_by_id(data["clientes"], task.get("cliente_id"))
        if client:
            return client.get("nome", "")
    if task.get("vinculo_tipo") == "lead" and task.get("vinculo_id"):
        lead = find_by_id(data["leads"], task.get("vinculo_id"))
        if lead:
            return lead.get("nome", "")
    return task.get("vinculo_nome") or "Sem vínculo"


def task_automation_reason(task):
    key = task.get("automation_key") or ""
    if key.startswith("lead_response:"):
        return "Criada porque o lead precisa da primeira resposta."
    if key.startswith("lead_followup:"):
        return "Criada porque o lead ficou sem avanço recente."
    if key.startswith("contract_signature:"):
        return "Criada porque há contrato pendente de assinatura."
    if key.startswith("relationship_contact:") and ":birthday:" in key:
        return "Criada porque o cliente faz aniversário hoje."
    if key.startswith("relationship_contact:") and ":no_contact:" in key:
        return "Criada porque o cliente está sem contato recente."
    if key.startswith("event_next_action:"):
        return "Criada a partir de um compromisso concluído na agenda."
    return ""


def automation_rule_info(task):
    key = task.get("automation_key") or ""
    if key.startswith("lead_response:"):
        return {"key": "lead_response", "label": "Primeira resposta ao lead", "note": "Lead novo precisa de contato rápido."}
    if key.startswith("lead_followup:"):
        return {"key": "lead_followup", "label": "Follow-up de lead", "note": "Lead sem avanço recente volta para a mesa."}
    if key.startswith("contract_signature:"):
        return {"key": "contract_signature", "label": "Assinatura de contrato", "note": "Contrato enviado ou em assinatura gera acompanhamento."}
    if key.startswith("relationship_contact:") and ":birthday:" in key:
        return {"key": "birthday", "label": "Aniversário de cliente", "note": "Cliente aniversariante vira lembrete de relacionamento."}
    if key.startswith("relationship_contact:") and ":no_contact:" in key:
        return {"key": "no_contact", "label": "Cliente sem contato", "note": "Relacionamento parado volta para acompanhamento."}
    if key.startswith("event_next_action:"):
        return {"key": "event_next_action", "label": "Próxima ação da agenda", "note": "Reunião concluída pode gerar tarefa de continuidade."}
    return {"key": "other", "label": "Outras automações", "note": "Tarefas criadas por regra interna do CRM."}


def complete_task_operational_effects(data, task):
    client, project, lead = task_history_targets(data, task)
    key = task.get("automation_key") or ""
    title = "Tarefa concluída"
    description = task.get("titulo") or task.get("text") or "Tarefa concluída"
    origin = "tarefa"
    update_client = True

    if key.startswith("lead_response:"):
        title = "Lead respondido"
        description = f"Primeira resposta registrada pela conclusão da tarefa: {description}."
        if lead:
            lead["ultima_interacao"] = today_br()
    elif key.startswith("lead_followup:"):
        title = "Follow-up de lead concluído"
        description = f"Follow-up tratado pela conclusão da tarefa: {description}."
        if lead:
            lead["ultima_interacao"] = today_br()
    elif key.startswith("contract_signature:"):
        title = "Acompanhamento de contrato"
        description = f"Acompanhamento de assinatura tratado pela conclusão da tarefa: {description}."
        if project:
            project.setdefault("contrato", {})["ultimo_followup_em"] = today_br()
    elif key.startswith("relationship_contact:"):
        title = "Relacionamento atualizado"
        description = f"Contato de relacionamento tratado pela conclusão da tarefa: {description}."
    elif key.startswith("event_next_action:"):
        title = "Próxima ação da agenda concluída"
        description = f"Próxima ação criada pela agenda foi concluída: {description}."
        origin = "agenda"
    elif task.get("origem") == "automacao":
        title = "Automação concluída"
        description = f"Tarefa automática concluída: {description}."

    register_operation_history(
        data,
        title,
        description,
        origin,
        f"task_done:{task.get('id')}:{task.get('done_at')}",
        client=client,
        project=project,
        lead=lead,
        update_client=update_client,
    )


def normalize_task(task, data):
    due = parse_date(task.get("prazo"))
    today = date.today()
    if task.get("done"):
        label = "Concluída"
    elif not due:
        label = "Sem data"
    elif due < today:
        label = f"Atrasada desde {due.strftime('%d/%m')}"
    elif due == today:
        label = "Hoje"
    else:
        label = due.strftime("%d/%m")
    task["label"] = label
    task["contexto"] = task_context(task, data)
    task["tone"] = {
        "Cobrança": "payment",
        "Follow-up": "relationship",
        "Projeto": "project",
        "Comercial": "commercial",
    }.get(task.get("tipo"), "neutral")
    task["calendar_url"] = google_calendar_url(task.get("titulo", "Tarefa"), task.get("prazo"), details=task.get("descricao", ""))
    client = find_by_id(data["clientes"], task.get("cliente_id"))
    lead = find_by_id(data["leads"], task.get("vinculo_id")) if task.get("vinculo_tipo") == "lead" else None
    if client:
        task["whatsapp_url"] = whatsapp_link(client.get("tel"), f"Olá, {client.get('nome', '').split(' ')[0]}!")
    elif lead:
        task["whatsapp_url"] = whatsapp_link(lead.get("tel"), f"Olá, {lead.get('nome', '').split(' ')[0]}! Recebi seu pedido e vou te chamar para entender melhor.")
    else:
        task["whatsapp_url"] = "#"
    if task.get("vinculo_tipo") == "cliente" and task.get("cliente_id"):
        task["link_url"] = url_for("client_detail", client_id=task["cliente_id"])
    elif task.get("vinculo_tipo") == "projeto" and task.get("vinculo_id"):
        task["link_url"] = url_for("project_detail", project_id=task["vinculo_id"])
    elif task.get("vinculo_tipo") == "lead":
        task["link_url"] = url_for("leads")
    elif task.get("tipo") == "Cobrança":
        task["link_url"] = url_for("receivables_page")
    else:
        task["link_url"] = ""
    task["open_url"] = task.get("link_url") or url_for("tasks_page")
    task["origin_label"] = "Automação" if task.get("origem") == "automacao" or task.get("automation_key") else "Manual"
    task["automation_reason"] = task_automation_reason(task)
    task["automation_rule"] = automation_rule_info(task) if task.get("automation_key") else None
    task["source_label"] = {
        "lead": "Lead",
        "cliente": "Cliente",
        "projeto": "Projeto",
    }.get(task.get("vinculo_tipo"), "Recebível" if task.get("tipo") == "Cobrança" else "Tarefa")
    automation_key = task.get("automation_key") or ""
    if automation_key.startswith("event_next_action:"):
        task["source_key"] = "agenda"
        task["source_label"] = "Agenda"
    elif automation_key.startswith("lead_") or task.get("vinculo_tipo") == "lead":
        task["source_key"] = "lead"
        task["source_label"] = "Lead"
    elif automation_key.startswith("contract_") or task.get("tipo") == "Contrato":
        task["source_key"] = "contrato"
        task["source_label"] = "Contrato"
    elif task.get("tipo") == "Cobrança":
        task["source_key"] = "cobranca"
        task["source_label"] = "Cobrança"
    elif task.get("vinculo_tipo") == "projeto":
        task["source_key"] = "projeto"
    elif task.get("vinculo_tipo") == "cliente":
        task["source_key"] = "cliente"
    else:
        task["source_key"] = "manual"
    return task


def normalize_event(event, data):
    item = dict(event)
    event_date = parse_date(item.get("data"))
    today = date.today()
    status = item.get("status") or "agendado"
    client = find_by_id(data.get("clientes", []), item.get("cliente_id"))
    project = find_by_id(data.get("projetos", []), item.get("projeto_id"))
    if client and not item.get("cliente"):
        item["cliente"] = client.get("nome")
    if project and not item.get("projeto"):
        item["projeto"] = project.get("nome")
    if project:
        item["open_url"] = url_for("project_detail", project_id=project.get("id"))
        item["context_label"] = project.get("nome")
        item["has_link"] = True
    elif client:
        item["open_url"] = url_for("client_detail", client_id=client.get("id"))
        item["context_label"] = client.get("nome")
        item["has_link"] = True
    else:
        item["open_url"] = url_for("agenda_page", _anchor=f"evento-{item.get('id')}")
        item["context_label"] = item.get("local") or item.get("link") or "Agenda"
        item["has_link"] = False
    item["is_unlinked"] = not item["has_link"]
    if status == "concluido":
        item["status_label"] = "Concluído"
        item["tone"] = "done"
    elif event_date and event_date < today:
        item["status_label"] = "Atrasado"
        item["tone"] = "overdue"
    elif event_date == today:
        item["status_label"] = "Hoje"
        item["tone"] = "today"
    else:
        item["status_label"] = "Agendado"
        item["tone"] = "upcoming"
    item["date_value"] = event_date
    item["data_fmt"] = format_date_br(item.get("data"))
    item["google_calendar_url"] = google_calendar_url(
        item.get("titulo") or "Compromisso",
        item.get("data"),
        item.get("hora"),
        item.get("hora_fim"),
        item.get("descricao") or item.get("observacoes", ""),
        item.get("local") or item.get("link", ""),
    )
    item["google_status_label"] = "Sincronizado" if item.get("google_event_id") else "Não sincronizado"
    item["link_suggestion"] = event_link_suggestion(item, data)
    return item


def build_agenda_board(data):
    events = [normalize_event(event, data) for event in data.get("eventos", [])]
    events = sorted(events, key=lambda e: (e.get("date_value") or date.max, e.get("hora", "")))
    open_events = [event for event in events if event.get("status") != "concluido"]
    today = date.today()
    return {
        "all": events,
        "open": open_events,
        "today": [event for event in open_events if event.get("date_value") == today],
        "overdue": [event for event in open_events if event.get("date_value") and event.get("date_value") < today],
        "upcoming": [event for event in open_events if not event.get("date_value") or event.get("date_value") > today],
        "done": [event for event in events if event.get("status") == "concluido"],
    }


def build_calendar_month(events, year=None, month=None):
    today = date.today()
    year = int(year or today.year)
    month = int(month or today.month)
    if month < 1 or month > 12:
        year, month = today.year, today.month
    first_day = date(year, month, 1)
    prev_month = first_day.replace(day=1) - timedelta(days=1)
    next_month = (first_day.replace(day=28) + timedelta(days=4)).replace(day=1)
    month_events = {}
    for event in events:
        event_date = event.get("date_value") or parse_date(event.get("data"))
        if not event_date or event_date.year != year or event_date.month != month:
            continue
        month_events.setdefault(event_date.day, []).append(event)
    weeks = []
    for week in calendar.Calendar(firstweekday=6).monthdatescalendar(year, month):
        week_items = []
        for day in week:
            day_events = sorted(month_events.get(day.day, []) if day.month == month else [], key=lambda e: e.get("hora") or "")
            week_items.append(
                {
                    "date": day,
                    "day": day.day,
                    "in_month": day.month == month,
                    "is_today": day == today,
                    "events": day_events,
                    "overflow": max(len(day_events) - 3, 0),
                }
            )
        weeks.append(week_items)
    return {
        "year": year,
        "month": month,
        "label": f"{['', 'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro'][month]} de {year}",
        "weeks": weeks,
        "prev_url": url_for("agenda_page", ano=prev_month.year, mes=prev_month.month),
        "next_url": url_for("agenda_page", ano=next_month.year, mes=next_month.month),
        "today_url": url_for("agenda_page"),
    }


def build_task_board(data):
    tasks = [normalize_task(t, data) for t in data.get("tarefas", [])]
    open_tasks = [t for t in tasks if not t.get("done")]
    done_tasks = [t for t in tasks if t.get("done")]
    today = date.today()
    overdue = [t for t in open_tasks if parse_date(t.get("prazo")) and parse_date(t.get("prazo")) < today]
    today_tasks = [t for t in open_tasks if parse_date(t.get("prazo")) == today]
    upcoming = [t for t in open_tasks if not parse_date(t.get("prazo")) or parse_date(t.get("prazo")) > today]
    without_deadline = [t for t in upcoming if not parse_date(t.get("prazo"))]
    upcoming_dated = [t for t in upcoming if parse_date(t.get("prazo"))]
    priority_weight = {"Alta": 0, "Média": 1, "Media": 1, "Baixa": 2}

    def task_sort_key(task):
        due = parse_date(task.get("prazo"))
        return (
            due or date.max,
            priority_weight.get(task.get("pri"), 1),
            0 if task.get("origem") == "automacao" or task.get("automation_key") else 1,
            str(task.get("titulo") or task.get("text") or "").lower(),
        )

    overdue = sorted(overdue, key=task_sort_key)
    today_tasks = sorted(today_tasks, key=task_sort_key)
    upcoming = sorted(upcoming, key=task_sort_key)
    without_deadline = sorted(without_deadline, key=task_sort_key)
    upcoming_dated = sorted(upcoming_dated, key=task_sort_key)
    next_candidates = overdue + today_tasks + upcoming_dated + without_deadline
    source_order = [
        ("lead", "Leads", "orçamentos e follow-ups comerciais"),
        ("agenda", "Agenda", "próximas ações criadas após reuniões"),
        ("cobranca", "Cobrança", "recebíveis e lembretes de pagamento"),
        ("contrato", "Contratos", "assinaturas e formalização"),
        ("projeto", "Projetos", "operação e entregas"),
        ("cliente", "Clientes", "relacionamento e contato"),
        ("manual", "Manuais", "tarefas criadas pela Vitória"),
    ]
    by_source = []
    for key, label, note in source_order:
        items = [t for t in open_tasks if t.get("source_key") == key]
        by_source.append({"key": key, "label": label, "note": note, "tasks": items, "count": len(items)})
    automation_tasks = [t for t in tasks if t.get("automation_key")]
    open_automation = [t for t in automation_tasks if not t.get("done")]
    today_automation = [t for t in open_automation if parse_date(t.get("prazo")) == today]
    done_automation = [t for t in automation_tasks if t.get("done")]
    rules_map = {}
    for task in automation_tasks:
        rule = task.get("automation_rule") or automation_rule_info(task)
        item = rules_map.setdefault(
            rule["key"],
            {
                "key": rule["key"],
                "label": rule["label"],
                "note": rule["note"],
                "open": 0,
                "done": 0,
                "today": 0,
            },
        )
        if task.get("done"):
            item["done"] += 1
        else:
            item["open"] += 1
            if parse_date(task.get("prazo")) == today:
                item["today"] += 1
    automation_rules = sorted(rules_map.values(), key=lambda item: (-item["open"], item["label"]))
    main_ids = {task.get("id") for task in overdue + today_tasks}
    automation_only = [task for task in open_automation if task.get("id") not in main_ids]
    focus_groups = [
        {"key": "overdue", "label": "Atrasadas", "note": "resolver primeiro", "tasks": overdue[:8], "count": len(overdue)},
        {"key": "today", "label": "Hoje", "note": "execucao do dia", "tasks": today_tasks[:8], "count": len(today_tasks)},
        {"key": "automation", "label": "Automacao", "note": "criadas pelo CRM", "tasks": automation_only[:8], "count": len(automation_only)},
        {"key": "without_deadline", "label": "Sem prazo", "note": "organizar depois", "tasks": without_deadline[:8], "count": len(without_deadline)},
    ]
    return {
        "today": today_tasks,
        "overdue": overdue,
        "upcoming": upcoming,
        "upcoming_dated": upcoming_dated,
        "without_deadline": without_deadline,
        "next_task": next_candidates[0] if next_candidates else None,
        "focus_groups": focus_groups,
        "by_source": by_source,
        "open_total": len(open_tasks),
        "automation": {
            "open": len(open_automation),
            "today": len(today_automation),
            "done_recent": len(done_automation[:8]),
            "rules": automation_rules,
        },
        "suggested": build_followups(data),
        "recent_done": sorted(done_tasks, key=lambda x: x.get("done_at") or "", reverse=True)[:8],
    }


def build_followups(data):
    items = []
    for client in data.get("clientes", []):
        last = parse_date(client.get("ultima_interacao"))
        days = (date.today() - last).days if last else None
        if days is not None and days < 30:
            continue
        items.append(
            {
                "titulo": f"Retomar contato com {client.get('nome')}",
                "subtitle": f"{days} dias sem contato." if days is not None else "Cliente sem última interação registrada.",
                "action_label": "WhatsApp",
                "action_url": whatsapp_link(client.get("tel"), f"Olá, {client.get('nome','').split(' ')[0]}! Passando para saber como você está."),
                "action_method": "get",
                "secondary_label": "Abrir cliente",
                "secondary_url": url_for("client_detail", client_id=client["id"]),
                "client_id": client.get("id"),
                "whatsapp_url": whatsapp_link(client.get("tel"), f"Olá, {client.get('nome','').split(' ')[0]}! Passando para saber como você está."),
                "days": days,
            }
        )
    return sorted(items, key=lambda item: item["days"] if item["days"] is not None else 999, reverse=True)[:5]


def relationship_data(data):
    today = date.today()
    birthdays_today = []
    birthdays_week = []
    no_contact = []
    for client in data.get("clientes", []):
        bday = parse_date(client.get("aniversario"))
        if bday:
            bday_this_year = bday.replace(year=today.year)
            delta = (bday_this_year - today).days
            if delta == 0:
                birthdays_today.append(client)
            elif 0 < delta <= 7:
                item = dict(client)
                item["dias"] = delta
                birthdays_week.append(item)
        last = parse_date(client.get("ultima_interacao"))
        days = (today - last).days if last else None
        if days is None or days >= 30:
            item = dict(client)
            item["dias_sem_contato"] = days
            item["dias_sem_contato_label"] = f"{days} dias" if days is not None else "sem registro"
            no_contact.append(item)
    return {"birthdays_today": birthdays_today, "birthdays_week": birthdays_week, "no_contact": no_contact}


def contract_label(contract):
    status = (contract or {}).get("status") or "Não iniciado"
    tone = "good" if status == "Assinado" else "watch" if status in ("Enviado", "Em assinatura") else "muted"
    return {"label": status, "tone": tone}


def enrich_project(project):
    project.setdefault("contrato", {})
    project.setdefault("pagamentos", [])
    project.setdefault("arquivos", [])
    project["contract_data"] = contract_label(project.get("contrato"))
    return project


def ensure_payment_ids(data):
    changed = 0
    for project in data.get("projetos", []):
        payments = project.setdefault("pagamentos", [])
        next_payment_id = next_id(payments)
        for payment in payments:
            if not payment.get("id"):
                payment["id"] = next_payment_id
                next_payment_id += 1
                changed += 1
    return changed


def append_project_payment(project, form):
    payments = project.setdefault("pagamentos", [])
    status = form.get("status") or "Pendente"
    payment = {
        "id": next_id(payments),
        "descricao": form.get("descricao") or "Parcela",
        "valor": form.get("valor") or 0,
        "vencimento": form.get("vencimento") or "",
        "status": status,
        "pago": status == "Pago",
        "pago_em": today_br() if status == "Pago" else "",
        "lembrete_dias_antes": form.get("lembrete_dias_antes") or 3,
        "ultimo_lembrete_em": "",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    payments.append(payment)
    return payment


def payment_summary(projects):
    items = []
    today = date.today()
    for project in projects:
        for payment in project.get("pagamentos", []) or []:
            status = payment.get("status") or "Pendente"
            due = parse_date(payment.get("vencimento"))
            calculated = "Pago" if status == "Pago" or payment.get("pago") else "Atrasado" if due and due < today else "Pendente"
            value = money_to_float(payment.get("valor"))
            item = dict(payment)
            item.update(
                {
                    "project_id": project.get("id"),
                    "project_name": project.get("nome"),
                    "status_calculado": calculated,
                    "valor_fmt": f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                    "lembrete_dias_antes": payment.get("lembrete_dias_antes", 3),
                }
            )
            items.append(item)
    open_items = [i for i in items if i["status_calculado"] != "Pago"]
    overdue = [i for i in items if i["status_calculado"] == "Atrasado"]
    next_due = sorted([(parse_date(i.get("vencimento")), i) for i in open_items if parse_date(i.get("vencimento"))], key=lambda x: x[0])
    open_total = sum(money_to_float(i.get("valor")) for i in open_items)
    return {
        "items": items,
        "pending_total": len(open_items),
        "pending_count": len(open_items),
        "overdue_total": len(overdue),
        "overdue_count": len(overdue),
        "next_due": next_due[0] if next_due else None,
        "open_total_fmt": f"R$ {open_total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
    }


def format_money(value):
    amount = money_to_float(value)
    return f"R$ {amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def build_receivables(data, filters=None):
    filters = filters or {}
    today = date.today()
    week_limit = today + timedelta(days=7)
    current_month_key = today.strftime("%Y-%m")
    items = []
    forecast = {}
    totals = {
        "open_value": 0.0,
        "overdue_value": 0.0,
        "week_value": 0.0,
        "paid_month_value": 0.0,
        "open_count": 0,
        "overdue_count": 0,
        "week_count": 0,
        "paid_month_count": 0,
    }
    for project in data.get("projetos", []):
        client = find_by_id(data.get("clientes", []), project.get("cliente_id"))
        for payment in project.get("pagamentos", []) or []:
            status = payment.get("status") or "Pendente"
            due = parse_date(payment.get("vencimento"))
            paid = status == "Pago" or payment.get("pago")
            amount = money_to_float(payment.get("valor"))
            if paid:
                calculated = "Pago"
            elif due and due < today:
                calculated = "Atrasado"
            elif due and today <= due <= week_limit:
                calculated = "Vence em breve"
            else:
                calculated = "Pendente"

            if not paid:
                totals["open_value"] += amount
                totals["open_count"] += 1
            if calculated == "Atrasado":
                totals["overdue_value"] += amount
                totals["overdue_count"] += 1
            if calculated == "Vence em breve":
                totals["week_value"] += amount
                totals["week_count"] += 1
            paid_date = parse_date(payment.get("pago_em") or payment.get("paid_at"))
            if paid and paid_date and paid_date.month == today.month and paid_date.year == today.year:
                totals["paid_month_value"] += amount
                totals["paid_month_count"] += 1
            if not paid and due:
                month_key = due.strftime("%Y-%m")
                month_label = due.strftime("%m/%Y")
                forecast.setdefault(month_key, {"label": month_label, "value": 0.0, "count": 0})
                forecast[month_key]["value"] += amount
                forecast[month_key]["count"] += 1

            client_name = client.get("nome") if client else project.get("cliente") or "Cliente sem vinculo"
            first_name = str(client_name).split(" ")[0]
            if calculated == "Atrasado":
                message = (
                    f"Olá, {first_name}! Passando para alinhar a parcela {str(payment.get('descricao') or '').lower()} "
                    f"do projeto {project.get('nome')}, que venceu em {format_date_br(payment.get('vencimento'))}. "
                    "Pode me confirmar, por favor, se já foi feito por aí?"
                )
            elif calculated == "Vence em breve":
                message = (
                    f"Olá, {first_name}! Tudo bem? Passando para lembrar, com carinho, que a parcela "
                    f"{str(payment.get('descricao') or '').lower()} do projeto {project.get('nome')} vence em "
                    f"{format_date_br(payment.get('vencimento'))}. Qualquer dúvida, fico à disposição."
                )
            else:
                message = (
                    f"Olá, {first_name}! Passando para lembrar, com carinho, que o vencimento de "
                    f"{str(payment.get('descricao') or 'uma parcela').lower()} do projeto {project.get('nome')} "
                    f"está previsto para {format_date_br(payment.get('vencimento')) or 'os próximos dias'}. "
                    "Qualquer dúvida, fico à disposição."
                )
            item = dict(payment)
            item.update(
                {
                    "project_id": project.get("id"),
                    "project_name": project.get("nome"),
                    "client_id": client.get("id") if client else "",
                    "client_name": client_name,
                    "client_phone": client.get("tel") if client else "",
                    "status_calculado": calculated,
                    "due_date": due,
                    "valor_num": amount,
                    "valor_fmt": format_money(amount),
                    "vencimento_fmt": format_date_br(payment.get("vencimento")),
                    "whatsapp_url": whatsapp_link(client.get("tel") if client else "", message),
                    "copy_message": message,
                }
            )
            items.append(item)

    order = {"Atrasado": 0, "Vence em breve": 1, "Pendente": 2, "Pago": 3}
    items = sorted(items, key=lambda item: (order.get(item.get("status_calculado"), 9), item.get("due_date") or date.max))
    status_filter = filters.get("status") or "todos"
    month_filter = filters.get("mes") or ""
    query = (filters.get("q") or "").strip().lower()
    if status_filter != "todos":
        items = [item for item in items if item.get("status_calculado") == status_filter]
    if month_filter:
        items = [item for item in items if item.get("due_date") and item["due_date"].strftime("%Y-%m") == month_filter]
    if query:
        items = [
            item
            for item in items
            if query in str(item.get("client_name", "")).lower()
            or query in str(item.get("project_name", "")).lower()
            or query in str(item.get("descricao", "")).lower()
        ]
    forecast_items = []
    for key in sorted(forecast.keys())[:6]:
        item = forecast[key]
        item["key"] = key
        item["value_fmt"] = format_money(item["value"])
        item["is_current"] = key == current_month_key
        forecast_items.append(item)
    if current_month_key not in forecast:
        forecast_items.insert(
            0,
            {
                "key": current_month_key,
                "label": today.strftime("%m/%Y"),
                "value": 0.0,
                "value_fmt": format_money(0),
                "count": 0,
                "is_current": True,
            },
        )
    forecast_items = sorted(forecast_items, key=lambda item: item["key"])[:6]
    selected_forecast = None
    if month_filter:
        selected_month = forecast.get(month_filter, {"label": datetime.strptime(month_filter + "-01", "%Y-%m-%d").strftime("%m/%Y"), "value": 0.0, "count": 0})
        selected_forecast = {
            "key": month_filter,
            "label": selected_month["label"],
            "value": selected_month["value"],
            "value_fmt": format_money(selected_month["value"]),
            "count": selected_month["count"],
            "is_current": month_filter == current_month_key,
        }
    totals.update(
        {
            "open_value_fmt": format_money(totals["open_value"]),
            "overdue_value_fmt": format_money(totals["overdue_value"]),
            "week_value_fmt": format_money(totals["week_value"]),
            "paid_month_value_fmt": format_money(totals["paid_month_value"]),
        }
    )
    return {"items": items, "totals": totals, "forecast": forecast_items, "selected_forecast": selected_forecast, "filters": filters}


def normalize_expense(expense):
    item = dict(expense)
    today = date.today()
    week_limit = today + timedelta(days=7)
    due = parse_date(item.get("vencimento"))
    status = item.get("status") or "Pendente"
    paid = status == "Pago" or item.get("pago")
    amount = money_to_float(item.get("valor"))
    if paid:
        calculated = "Pago"
    elif due and due < today:
        calculated = "Atrasado"
    elif due and today <= due <= week_limit:
        calculated = "Vence em breve"
    else:
        calculated = "Pendente"
    item.update(
        {
            "status_calculado": calculated,
            "due_date": due,
            "valor_num": amount,
            "valor_fmt": format_money(amount),
            "vencimento_fmt": format_date_br(item.get("vencimento")),
            "recorrente_label": "Recorrente" if item.get("recorrente") else "Avulsa",
        }
    )
    return item


def build_expenses(data, filters=None):
    filters = filters or {}
    today = date.today()
    items = [normalize_expense(expense) for expense in data.get("despesas", [])]
    totals = {
        "open_value": 0.0,
        "overdue_value": 0.0,
        "week_value": 0.0,
        "paid_month_value": 0.0,
        "month_value": 0.0,
        "open_count": 0,
        "overdue_count": 0,
        "week_count": 0,
        "paid_month_count": 0,
        "month_count": 0,
    }
    for item in items:
        paid = item.get("status_calculado") == "Pago"
        due = item.get("due_date")
        paid_date = parse_date(item.get("pago_em") or item.get("paid_at"))
        amount = item.get("valor_num", 0.0)
        if not paid:
            totals["open_value"] += amount
            totals["open_count"] += 1
        if item.get("status_calculado") == "Atrasado":
            totals["overdue_value"] += amount
            totals["overdue_count"] += 1
        if item.get("status_calculado") == "Vence em breve":
            totals["week_value"] += amount
            totals["week_count"] += 1
        if due and due.month == today.month and due.year == today.year:
            totals["month_value"] += amount
            totals["month_count"] += 1
        if paid and paid_date and paid_date.month == today.month and paid_date.year == today.year:
            totals["paid_month_value"] += amount
            totals["paid_month_count"] += 1

    status_filter = filters.get("status") or "todos"
    month_filter = filters.get("mes") or ""
    query = (filters.get("q") or "").strip().lower()
    if status_filter != "todos":
        items = [item for item in items if item.get("status_calculado") == status_filter]
    if month_filter:
        items = [item for item in items if item.get("due_date") and item["due_date"].strftime("%Y-%m") == month_filter]
    if query:
        items = [
            item
            for item in items
            if query in str(item.get("descricao", "")).lower()
            or query in str(item.get("categoria", "")).lower()
            or query in str(item.get("observacoes", "")).lower()
        ]
    order = {"Atrasado": 0, "Vence em breve": 1, "Pendente": 2, "Pago": 3}
    items = sorted(items, key=lambda item: (order.get(item.get("status_calculado"), 9), item.get("due_date") or date.max))
    totals.update({f"{key}_fmt": format_money(value) for key, value in totals.items() if key.endswith("_value")})
    return {"items": items, "totals": totals, "filters": filters}


def build_financial(data, filters=None):
    filters = filters or {}
    month_key = filters.get("mes") or date.today().strftime("%Y-%m")
    receivables = build_receivables(data, {"status": "todos", "mes": month_key, "q": ""})
    expenses = build_expenses(data, filters)
    month_receivable_value = sum(item.get("valor_num", 0.0) for item in receivables.get("items", []))
    month_expense_items = [item for item in [normalize_expense(e) for e in data.get("despesas", [])] if item.get("due_date") and item["due_date"].strftime("%Y-%m") == month_key]
    month_expense_value = sum(item.get("valor_num", 0.0) for item in month_expense_items)
    paid_expense_value = sum(item.get("valor_num", 0.0) for item in month_expense_items if item.get("status_calculado") == "Pago")
    paid_receivable_value = sum(item.get("valor_num", 0.0) for item in receivables.get("items", []) if item.get("status_calculado") == "Pago")
    return {
        "month": month_key,
        "month_label": datetime.strptime(month_key + "-01", "%Y-%m-%d").strftime("%m/%Y"),
        "receivables": receivables,
        "expenses": expenses,
        "summary": {
            "receivable_value": month_receivable_value,
            "receivable_value_fmt": format_money(month_receivable_value),
            "expense_value": month_expense_value,
            "expense_value_fmt": format_money(month_expense_value),
            "expected_balance": month_receivable_value - month_expense_value,
            "expected_balance_fmt": format_money(month_receivable_value - month_expense_value),
            "real_balance": paid_receivable_value - paid_expense_value,
            "real_balance_fmt": format_money(paid_receivable_value - paid_expense_value),
        },
        "filters": filters,
    }


def client_snapshot(client, projects):
    active = [p for p in projects if p.get("status") != "Entregue"]
    completed = [p for p in projects if p.get("status") == "Entregue"]
    total_value = sum(money_to_float(p.get("valor")) for p in projects)
    deadlines = sorted([(parse_date(p.get("prazo")), p) for p in active if parse_date(p.get("prazo"))], key=lambda x: x[0])
    last = parse_date(client.get("ultima_interacao"))
    days = (date.today() - last).days if last else None
    badge = {"label": "Contato em dia", "tone": "good"} if days is not None and days <= 30 else {"label": "Retomar", "tone": "watch"} if days else {"label": "Sem classificação", "tone": "neutral"}
    return {
        "active_total": len(active),
        "projects_total": len(projects),
        "completed_total": len(completed),
        "total_value": total_value,
        "next_deadline": deadlines[0] if deadlines else None,
        "no_contact_days": days,
        "relationship_badge": badge,
    }


def contracts_for_client(projects):
    items = []
    counts = {"Assinado": 0, "Enviado": 0, "Não iniciado": 0}
    for project in projects:
        contract = project.get("contrato", {}) or {}
        status = contract.get("status") or "Não iniciado"
        counts[status] = counts.get(status, 0) + 1
        label = contract_label(contract)
        items.append(
            {
                "project_id": project.get("id"),
                "project_name": project.get("nome"),
                "status": status,
                "label": label["label"],
                "tone": label["tone"],
                "modelo": contract.get("modelo") or "Contrato padrão Vitória",
                "emitido_em": contract.get("emitido_em") or "",
                "assinado_em": contract.get("assinado_em") or "",
                "whatsapp_url": "#",
                "email_url": "#",
            }
        )
    return {
        "total": len(items),
        "signed_total": counts.get("Assinado", 0),
        "pending_total": len(items) - counts.get("Assinado", 0),
        "counts": counts,
        "contract_items": items,
    }


def build_client_timeline(client, projects, tasks, financeiro, contracts):
    items = []
    for item in client.get("historico", []) or []:
        items.append(
            {
                "date": parse_date(item.get("data")) or date.min,
                "data": item.get("data") or "",
                "tipo": "Histórico",
                "titulo": item.get("titulo") or "Interação",
                "descricao": item.get("descricao") or "",
                "tone": "relationship",
                "url": "",
            }
        )
    for project in projects:
        if project.get("prazo"):
            items.append(
                {
                    "date": parse_date(project.get("prazo")) or date.max,
                    "data": format_date_br(project.get("prazo")),
                    "tipo": "Projeto",
                    "titulo": project.get("nome") or "Projeto",
                    "descricao": f"{project.get('status') or 'Sem status'} · {project.get('progresso') or 0}% concluído",
                    "tone": "project",
                    "url": url_for("project_detail", project_id=project.get("id")),
                }
            )
    for task in tasks:
        if task.get("done"):
            items.append(
                {
                    "date": parse_date(task.get("done_at")) or date.min,
                    "data": task.get("done_at") or "",
                    "tipo": "Tarefa",
                    "titulo": task.get("titulo") or task.get("text") or "Tarefa concluída",
                    "descricao": task.get("descricao") or task.get("tipo") or "",
                    "tone": "task",
                    "url": task.get("open_url") or "",
                }
            )
    for payment in financeiro.get("items", []):
        if payment.get("status_calculado") != "Pago":
            items.append(
                {
                    "date": parse_date(payment.get("vencimento")) or date.max,
                    "data": format_date_br(payment.get("vencimento")),
                    "tipo": "Recebível",
                    "titulo": payment.get("descricao") or "Parcela pendente",
                    "descricao": f"{payment.get('project_name')} · {payment.get('valor_fmt')} · {payment.get('status_calculado')}",
                    "tone": "payment",
                    "url": url_for("receivables_page"),
                }
            )
    for contract in contracts.get("contract_items", []):
        if contract.get("status") != "Assinado":
            items.append(
                {
                    "date": parse_date(contract.get("emitido_em")) or date.max,
                    "data": contract.get("emitido_em") or "",
                    "tipo": "Contrato",
                    "titulo": contract.get("project_name") or "Contrato pendente",
                    "descricao": f"{contract.get('modelo')} · {contract.get('status')}",
                    "tone": "contract",
                    "url": url_for("project_detail", project_id=contract.get("project_id")),
                }
            )
    return sorted(items, key=lambda item: item.get("date") or date.min, reverse=True)[:10]


def client_next_action(client, snapshot, financeiro, contracts, tasks):
    first = str(client.get("nome") or "cliente").split(" ")[0]
    open_tasks = [task for task in tasks if not task.get("done")]
    overdue_tasks = [task for task in open_tasks if parse_date(task.get("prazo")) and parse_date(task.get("prazo")) < date.today()]
    if financeiro.get("overdue_count"):
        return {
            "label": "Acompanhar pagamento atrasado",
            "note": f"{financeiro.get('overdue_count')} parcela(s) atrasada(s).",
            "tone": "payment",
            "primary_label": "Abrir recebíveis",
            "primary_url": url_for("receivables_page"),
            "secondary_label": "WhatsApp",
            "secondary_url": whatsapp_link(client.get("tel"), f"Olá, {first}! Passando para alinhar uma parcela pendente do seu projeto."),
        }
    if contracts.get("pending_total"):
        pending = next((item for item in contracts.get("contract_items", []) if item.get("status") != "Assinado"), None)
        return {
            "label": "Acompanhar contrato",
            "note": f"{pending.get('project_name') if pending else 'Contrato'} ainda pendente.",
            "tone": "contract",
            "primary_label": "Abrir projeto",
            "primary_url": url_for("project_detail", project_id=pending.get("project_id")) if pending else "#",
            "secondary_label": "WhatsApp",
            "secondary_url": whatsapp_link(client.get("tel"), f"Olá, {first}! Passando para lembrar da assinatura do contrato."),
        }
    if overdue_tasks:
        task = overdue_tasks[0]
        return {
            "label": "Resolver tarefa atrasada",
            "note": task.get("titulo") or task.get("text") or "Tarefa pendente.",
            "tone": "task",
            "primary_label": "Abrir tarefa",
            "primary_url": task.get("open_url") or url_for("tasks_page"),
            "secondary_label": "",
            "secondary_url": "",
        }
    if snapshot.get("no_contact_days") is None or snapshot.get("no_contact_days", 0) >= 30:
        return {
            "label": "Retomar relacionamento",
            "note": "Cliente sem contato recente.",
            "tone": "relationship",
            "primary_label": "WhatsApp",
            "primary_url": whatsapp_link(client.get("tel"), f"Olá, {first}! Passando para saber como você está e se posso te ajudar em algo por aqui."),
            "secondary_label": "Registrar contato",
            "secondary_url": url_for("quick_client_contact", client_id=client.get("id")),
        }
    return {
        "label": "Relacionamento em dia",
        "note": "Sem ação crítica agora.",
        "tone": "good",
        "primary_label": "Registrar contato",
        "primary_url": url_for("quick_client_contact", client_id=client.get("id")),
        "secondary_label": "",
        "secondary_url": "",
    }


def project_stage_view(project):
    stages = project.get("etapas", []) or []
    next_index = None
    for index, stage in enumerate(stages):
        if not stage.get("done"):
            next_index = index
            break
    items = []
    for index, stage in enumerate(stages):
        if stage.get("done"):
            state = "done"
            state_label = "Feito"
        elif index == next_index:
            state = "current"
            state_label = "Em andamento"
        else:
            state = "next"
            state_label = "Próximo"
        items.append({**stage, "index": index, "state": state, "state_label": state_label})
    current = items[next_index] if next_index is not None and items else None
    return {"items": items, "current": current, "completed": len([item for item in items if item.get("done")]), "total": len(items)}


def project_next_action(project, client, payment_data, contract_data, linked_tasks, stage_data):
    overdue = [item for item in payment_data.get("items", []) if item.get("status_calculado") == "Atrasado"]
    if overdue:
        return {
            "label": "Acompanhar recebível atrasado",
            "note": f"{overdue[0].get('descricao') or 'Parcela'} · {overdue[0].get('valor_fmt')}",
            "tone": "payment",
            "primary_label": "Abrir recebíveis",
            "primary_url": url_for("receivables_page"),
        }
    contract_status = (project.get("contrato") or {}).get("status") or "Não iniciado"
    if contract_status in ("Enviado", "Em assinatura"):
        return {
            "label": "Lembrar assinatura do contrato",
            "note": f"Contrato {contract_status.lower()} para {project.get('cliente') or 'cliente'}.",
            "tone": "contract",
            "primary_label": "WhatsApp",
            "primary_url": contract_data.get("whatsapp_url") or "#",
        }
    open_tasks = [task for task in linked_tasks if not task.get("done")]
    overdue_tasks = [task for task in open_tasks if parse_date(task.get("prazo")) and parse_date(task.get("prazo")) < date.today()]
    if overdue_tasks:
        task = overdue_tasks[0]
        return {
            "label": "Resolver tarefa atrasada",
            "note": task.get("titulo") or task.get("text") or "Tarefa vinculada ao projeto.",
            "tone": "task",
            "primary_label": "Abrir tarefa",
            "primary_url": task.get("open_url") or url_for("tasks_page"),
        }
    if stage_data.get("current"):
        current = stage_data["current"]
        return {
            "label": f"Avançar etapa: {current.get('nome')}",
            "note": "Revisar pendências e marcar como feito quando estiver aprovado.",
            "tone": "project",
            "primary_label": "Ver etapas",
            "primary_url": f"#etapas",
        }
    return {
        "label": "Projeto sem pendência crítica",
        "note": "Boa hora para revisar histórico, arquivos e próximos combinados.",
        "tone": "good",
        "primary_label": "Abrir cliente",
        "primary_url": url_for("client_detail", client_id=client.get("id")) if client else url_for("projects"),
    }


def build_project_timeline(project, payment_data, linked_tasks):
    items = []
    for item in project.get("historico", []) or []:
        items.append(
            {
                "date": parse_date(item.get("data")) or date.min,
                "data": item.get("data") or "",
                "tipo": "Histórico",
                "titulo": item.get("titulo") or "Registro",
                "descricao": item.get("descricao") or "",
                "tone": "relationship",
            }
        )
    for stage in project.get("etapas", []) or []:
        if stage.get("done"):
            items.append(
                {
                    "date": parse_date(stage.get("data")) or date.min,
                    "data": stage.get("data") or "",
                    "tipo": "Etapa",
                    "titulo": stage.get("nome"),
                    "descricao": "Etapa marcada como concluída.",
                    "tone": "project",
                }
            )
    for task in linked_tasks:
        if task.get("done"):
            items.append(
                {
                    "date": parse_date(task.get("done_at")) or date.min,
                    "data": task.get("done_at") or "",
                    "tipo": "Tarefa",
                    "titulo": task.get("titulo") or task.get("text"),
                    "descricao": task.get("descricao") or task.get("tipo") or "",
                    "tone": "task",
                }
            )
    for item in payment_data.get("items", []):
        if item.get("status_calculado") == "Pago":
            items.append(
                {
                    "date": parse_date(item.get("pago_em")) or date.min,
                    "data": item.get("pago_em") or "",
                    "tipo": "Recebível",
                    "titulo": item.get("descricao") or "Parcela paga",
                    "descricao": f"{item.get('valor_fmt')} · pago",
                    "tone": "payment",
                }
            )
    contract = project.get("contrato", {}) or {}
    if contract.get("status") and contract.get("status") != "Não iniciado":
        items.append(
            {
                "date": parse_date(contract.get("assinado_em") or contract.get("emitido_em")) or date.min,
                "data": contract.get("assinado_em") or contract.get("emitido_em") or "",
                "tipo": "Contrato",
                "titulo": contract.get("status"),
                "descricao": contract.get("modelo") or "Contrato padrão Vitória",
                "tone": "contract",
            }
        )
    return sorted(items, key=lambda item: item.get("date") or date.min, reverse=True)[:10]


def activity_tone(kind):
    return {
        "Recebível": "payment",
        "Pagamento": "payment",
        "Despesa": "payment",
        "Contrato": "contract",
        "Agenda": "agenda",
        "Tarefa": "task",
        "Lead": "lead",
        "Projeto": "project",
        "Cliente": "relationship",
        "Histórico": "relationship",
    }.get(kind, "relationship")


def build_activity_center(data, filters=None):
    filters = filters or {}
    kind_filter = filters.get("tipo") or "todos"
    query = (filters.get("q") or "").strip().lower()
    activities = []

    def add_activity(kind, title, description="", when="", url="", context="", source_key=""):
        text = " ".join([str(title or ""), str(description or ""), str(context or ""), kind]).lower()
        if kind_filter != "todos" and kind != kind_filter:
            return
        if query and query not in text:
            return
        activities.append(
            {
                "kind": kind,
                "title": title or kind,
                "description": description or "",
                "data": when or "",
                "date": parse_date(when) or date.min,
                "url": url or "",
                "context": context or "",
                "tone": activity_tone(kind),
                "source_key": source_key,
            }
        )

    for client in data.get("clientes", []):
        client_url = url_for("client_detail", client_id=client.get("id"))
        for entry in client.get("historico", []) or []:
            add_activity(
                "Cliente",
                entry.get("titulo") or "Histórico",
                entry.get("descricao") or "",
                entry.get("data") or "",
                client_url,
                client.get("nome") or "",
                f"client:{client.get('id')}:{entry.get('source_key') or entry.get('titulo')}",
            )

    for project in data.get("projetos", []):
        project_url = url_for("project_detail", project_id=project.get("id"))
        for entry in project.get("historico", []) or []:
            add_activity(
                "Projeto",
                entry.get("titulo") or "Registro",
                entry.get("descricao") or "",
                entry.get("data") or "",
                project_url,
                f"{project.get('cliente') or ''} · {project.get('nome') or ''}",
                f"project:{project.get('id')}:{entry.get('source_key') or entry.get('titulo')}",
            )
        for payment in project.get("pagamentos", []) or []:
            if payment.get("status") == "Pago" or payment.get("pago"):
                add_activity(
                    "Recebível",
                    payment.get("descricao") or "Parcela paga",
                    f"{project.get('nome')} · {format_money(money_to_float(payment.get('valor')))} pago",
                    payment.get("pago_em") or "",
                    url_for("receivables_page"),
                    project.get("cliente") or "",
                    f"payment:{project.get('id')}:{payment.get('id')}",
                )
        contract = project.get("contrato", {}) or {}
        if contract.get("status") and contract.get("status") != "Não iniciado":
            add_activity(
                "Contrato",
                contract.get("status"),
                contract.get("modelo") or f"Contrato do projeto {project.get('nome')}",
                contract.get("status_atualizado_em") or contract.get("assinado_em") or contract.get("emitido_em") or "",
                project_url,
                f"{project.get('cliente') or ''} · {project.get('nome') or ''}",
                f"contract:{project.get('id')}:{contract.get('status')}",
            )

    for lead in data.get("leads", []):
        for entry in lead.get("historico", []) or []:
            add_activity(
                "Lead",
                entry.get("titulo") or "Lead",
                entry.get("descricao") or "",
                entry.get("data") or "",
                url_for("leads"),
                lead.get("nome") or "",
                f"lead:{lead.get('id')}:{entry.get('source_key') or entry.get('titulo')}",
            )

    for task in data.get("tarefas", []):
        if task.get("done"):
            normalized = normalize_task(dict(task), data)
            add_activity(
                "Tarefa",
                task.get("titulo") or task.get("text") or "Tarefa concluída",
                task.get("descricao") or task.get("tipo") or "",
                task.get("done_at") or "",
                normalized.get("open_url") or url_for("tasks_page"),
                normalized.get("contexto") or "",
                f"task:{task.get('id')}",
            )

    for event in data.get("eventos", []):
        normalized = normalize_event(event, data)
        if event.get("status") == "concluido":
            add_activity(
                "Agenda",
                event.get("titulo") or "Compromisso concluído",
                f"{format_date_br(event.get('data')) or ''} · {event.get('hora') or 'sem horário'}",
                event.get("concluido_em") or event.get("data") or "",
                normalized.get("open_url") or url_for("agenda_page"),
                normalized.get("context_label") or "",
                f"event:{event.get('id')}",
            )

    deduped = {}
    for item in activities:
        key = item.get("source_key") or f"{item['kind']}:{item['title']}:{item['data']}:{item['context']}"
        deduped.setdefault(key, item)
    items = sorted(deduped.values(), key=lambda item: (item.get("date") or date.min, item.get("title") or ""), reverse=True)
    summary = {
        "total": len(items),
        "clientes": len([i for i in items if i["kind"] == "Cliente"]),
        "projetos": len([i for i in items if i["kind"] == "Projeto"]),
        "leads": len([i for i in items if i["kind"] == "Lead"]),
        "financeiro": len([i for i in items if i["kind"] == "Recebível"]),
    }
    return {"items": items[:80], "summary": summary, "filters": filters, "types": ["todos", "Cliente", "Projeto", "Lead", "Tarefa", "Agenda", "Recebível", "Contrato"]}


def build_contract_actions(data):
    actions = []
    today = date.today()
    for project in data.get("projetos", []):
        contract = project.get("contrato", {}) or {}
        status = contract.get("status") or "Não iniciado"
        if status not in ("Enviado", "Em assinatura"):
            continue
        reminder_days = int(contract.get("lembrete_assinatura_dias") or 3)
        last_followup = parse_date(contract.get("ultimo_followup_em"))
        emitted = parse_date(contract.get("emitido_em"))
        base_date = last_followup or emitted
        if base_date and (today - base_date).days < reminder_days:
            continue
        client = find_by_id(data.get("clientes", []), project.get("cliente_id"))
        client_name = client.get("nome") if client else project.get("cliente") or "Cliente"
        first_name = str(client_name).split(" ")[0]
        actions.append(
            {
                "project_id": project.get("id"),
                "project_name": project.get("nome"),
                "client_name": client_name,
                "status": status,
                "days": (today - base_date).days if base_date else 0,
                "action_url": url_for("project_detail", project_id=project.get("id")),
                "whatsapp_url": whatsapp_link(client.get("tel") if client else "", f"Olá, {first_name}! Passando para lembrar da assinatura do contrato do projeto {project.get('nome')}."),
            }
        )
    return actions


def has_open_automation_task(data, automation_key):
    return any(
        task.get("automation_key") == automation_key and not task.get("done")
        for task in data.get("tarefas", [])
    )


def find_open_automation_task(data, automation_key):
    for task in data.get("tarefas", []):
        if task.get("automation_key") == automation_key and not task.get("done"):
            return task
    return None


def complete_lead_automation_tasks(data, lead_id, keys):
    for task in data.get("tarefas", []):
        if task.get("automation_key") in [f"{key}:{lead_id}" for key in keys] and not task.get("done"):
            task["done"] = True
            task["status"] = "Concluída"
            task["done_at"] = today_br()


def create_lead_response_task(data, lead, title="Responder orçamento"):
    key = f"lead_response:{lead.get('id')}"
    if has_open_automation_task(data, key):
        return None
    task = {
        "id": next_id(data["tarefas"]),
        "titulo": title,
        "text": title,
        "descricao": f"Entrar em contato com {lead.get('nome')} pelo WhatsApp e dar sequência ao atendimento.",
        "tipo": "Comercial",
        "pri": "Alta",
        "prazo": date.today().isoformat(),
        "prazo_contato_at": lead.get("primeiro_contato_prazo") or "",
        "done": False,
        "status": "Pendente",
        "responsavel": LEAD_OWNER_DEFAULT,
        "vinculo_tipo": "lead",
        "vinculo_id": lead.get("id"),
        "vinculo_nome": lead.get("nome"),
        "cliente_id": "",
        "origem": "automacao",
        "automation_key": key,
        "done_at": "",
    }
    data["tarefas"].append(task)
    return task


def lead_days_since_interaction(lead):
    last = parse_date(lead.get("ultima_interacao") or lead.get("created_at") or lead.get("data"))
    return (date.today() - last).days if last else None


def parse_datetime_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def lead_first_contact_deadline(created_at_iso):
    created = parse_datetime_iso(created_at_iso) or datetime.now()
    return (created + timedelta(minutes=LEAD_FIRST_CONTACT_SLA_MINUTES)).isoformat(timespec="seconds")


def lead_sla_minutes_without_action(lead):
    stage_key = lead_stage_key(lead)
    if stage_key != "new":
        return 0
    created = parse_datetime_iso(lead.get("created_at"))
    if not created:
        return 0
    return max(0, int((datetime.now() - created).total_seconds() // 60))


def build_lead_whatsapp_message(lead):
    first = str(lead.get("nome") or "").split(" ")[0] or "tudo bem"
    stage_key = lead_stage_key(lead)
    if stage_key == "new":
        return f"Ol, {first}! Recebi seu pedido de oramento e vou te chamar para entender melhor seu projeto."
    if stage_key == "contacted":
        return f"Ol, {first}! Passando para alinhar os prximos passos do seu projeto."
    if stage_key == "briefing":
        return f"Ol, {first}! Vamos confirmar os pontos do briefing para avanarmos com segurana."
    if stage_key == "proposal":
        return f"Ol, {first}! Queria te ajudar com qualquer dvida para avanarmos com a proposta."
    return f"Ol, {first}! Tudo bem por a?"


def is_stale_lead(lead):
    stage_key = lead_stage_key(lead)
    days = lead_days_since_interaction(lead)
    return stage_key not in ("lost", "closed", "future") and days is not None and days >= 2


def create_lead_followup_task(data, lead):
    key = f"lead_followup:{lead.get('id')}"
    response_task = find_open_automation_task(data, f"lead_response:{lead.get('id')}")
    days = lead_days_since_interaction(lead)
    if response_task:
        response_task["titulo"] = "Fazer follow-up do lead"
        response_task["text"] = "Fazer follow-up do lead"
        response_task["descricao"] = f"{lead.get('nome')} está sem avanço há {days} dias. Chamar no WhatsApp e definir o próximo passo."
        response_task["pri"] = "Alta"
        response_task["prazo"] = date.today().isoformat()
        return response_task
    if has_open_automation_task(data, key):
        return None
    task = {
        "id": next_id(data["tarefas"]),
        "titulo": "Fazer follow-up do lead",
        "text": "Fazer follow-up do lead",
        "descricao": f"{lead.get('nome')} está sem avanço há {days} dias. Chamar no WhatsApp e definir o próximo passo.",
        "tipo": "Comercial",
        "pri": "Alta",
        "prazo": date.today().isoformat(),
        "done": False,
        "status": "Pendente",
        "responsavel": "Vitória Uardon",
        "vinculo_tipo": "lead",
        "vinculo_id": lead.get("id"),
        "vinculo_nome": lead.get("nome"),
        "cliente_id": "",
        "origem": "automacao",
        "automation_key": key,
        "done_at": "",
    }
    data["tarefas"].append(task)
    return task


def ensure_lead_followup_tasks(data):
    created = 0
    for lead in data.get("leads", []):
        if is_stale_lead(lead) and create_lead_followup_task(data, lead):
            created += 1
    return created


def create_contract_signature_task(data, contract_action):
    base_key = f"{contract_action.get('status')}:{contract_action.get('days')}"
    key = f"contract_signature:{contract_action.get('project_id')}:{base_key}"
    if has_automation_task(data, key):
        return None
    project = find_by_id(data.get("projetos", []), contract_action.get("project_id"))
    if not project:
        return None
    client = find_by_id(data.get("clientes", []), project.get("cliente_id"))
    task = {
        "id": next_id(data["tarefas"]),
        "titulo": "Acompanhar assinatura do contrato",
        "text": "Acompanhar assinatura do contrato",
        "descricao": f"Contrato do projeto {project.get('nome')} está como {contract_action.get('status')}. Chamar o cliente e confirmar assinatura.",
        "tipo": "Contrato",
        "pri": "Alta",
        "prazo": date.today().isoformat(),
        "done": False,
        "status": "Pendente",
        "responsavel": "Vitória Uardon",
        "vinculo_tipo": "projeto",
        "vinculo_id": project.get("id"),
        "vinculo_nome": project.get("nome"),
        "cliente_id": client.get("id") if client else "",
        "origem": "automacao",
        "automation_key": key,
        "done_at": "",
    }
    data["tarefas"].append(task)
    return task


def ensure_contract_signature_tasks(data):
    created = 0
    for action in build_contract_actions(data)[:3]:
        if create_contract_signature_task(data, action):
            created += 1
    return created


def create_relationship_contact_task(data, client, reason, key_suffix, priority="Média"):
    key = f"relationship_contact:{client.get('id')}:{key_suffix}"
    if has_automation_task(data, key):
        return None
    task = {
        "id": next_id(data["tarefas"]),
        "titulo": reason,
        "text": reason,
        "descricao": f"Entrar em contato com {client.get('nome')} e registrar a interação no cliente.",
        "tipo": "Follow-up",
        "pri": priority,
        "prazo": date.today().isoformat(),
        "done": False,
        "status": "Pendente",
        "responsavel": "Vitória Uardon",
        "vinculo_tipo": "cliente",
        "vinculo_id": client.get("id"),
        "vinculo_nome": client.get("nome"),
        "cliente_id": client.get("id"),
        "origem": "automacao",
        "automation_key": key,
        "done_at": "",
    }
    data["tarefas"].append(task)
    return task


def ensure_relationship_tasks(data):
    relationship = relationship_data(data)
    created = 0
    year = date.today().year
    month_key = date.today().strftime("%Y-%m")
    for client in relationship["birthdays_today"][:2]:
        if create_relationship_contact_task(data, client, "Enviar mensagem de aniversário", f"birthday:{year}", "Média"):
            created += 1
    for client in relationship["no_contact"][:3]:
        if create_relationship_contact_task(data, client, "Retomar relacionamento com cliente", f"no_contact:{month_key}", "Baixa"):
            created += 1
    return created


def ensure_daily_automation_tasks(data):
    created = 0
    created += ensure_lead_followup_tasks(data)
    created += ensure_contract_signature_tasks(data)
    created += ensure_relationship_tasks(data)
    return created


def lead_stage_key(lead):
    status = (lead.get("status") or "novo").strip().lower()
    stage = (lead.get("etapa") or "").strip().lower()
    if status == "perdido":
        return "lost"
    if status == "futuro":
        return "future"
    if status == "convertido" or "convertido" in stage or status == "fechado":
        return "closed"
    if "proposta" in stage:
        return "proposal"
    if "briefing" in stage or "reuni" in stage or "medi" in stage:
        return "briefing"
    if "contato" in stage or status in ("em contato", "contato feito"):
        return "contacted"
    return "new"


def build_lead_pipeline(leads):
    columns = [
        {"key": "new", "stage": "novo", "label": "Novo", "note": "orcamentos e contatos recentes", "items": []},
        {"key": "contacted", "stage": "contato", "label": "Contato feito", "note": "ja teve primeira resposta", "items": []},
        {"key": "briefing", "stage": "briefing", "label": "Briefing marcado", "note": "proxima conversa agendada", "items": []},
        {"key": "proposal", "stage": "proposta", "label": "Proposta enviada", "note": "aguardando decisao", "items": []},
        {"key": "closed", "stage": "fechado", "label": "Fechado", "note": "convertido em cliente", "items": []},
    ]
    by_key = {column["key"]: column for column in columns}
    future = []
    lost = []
    for lead in leads:
        item = dict(lead)
        item["stage_key"] = lead_stage_key(item)
        item["days_since_interaction"] = lead_days_since_interaction(item)
        item["is_stale"] = is_stale_lead(item)
        item["stale_label"] = f"{item['days_since_interaction']} dias sem avanço" if item["is_stale"] else ""
        item["owner_name"] = item.get("responsavel") or LEAD_OWNER_DEFAULT
        item["sla_minutes"] = lead_sla_minutes_without_action(item)
        item["sla_overdue"] = item["sla_minutes"] > LEAD_FIRST_CONTACT_SLA_MINUTES
        item["sla_label"] = f"SLA estourado: {item['sla_minutes']} min sem resposta" if item["sla_overdue"] else ""
        item["whatsapp_url"] = whatsapp_link(item.get("tel"), build_lead_whatsapp_message(item))
        if item["stage_key"] == "future":
            future.append(item)
        elif item["stage_key"] == "lost":
            lost.append(item)
        elif item["stage_key"] in by_key:
            by_key[item["stage_key"]]["items"].append(item)
    return {"columns": columns, "future": future, "lost": lost}


def build_commercial_metrics(data, board, pipeline):
    today = date.today()
    open_leads = [lead for lead in data.get("leads", []) if lead_stage_key(lead) not in ("lost", "closed")]
    budget_leads = [
        lead
        for lead in open_leads
        if (lead.get("origem") or "").lower() == "instagram"
        and (lead.get("etapa") or "").lower() == "orçamento recebido"
    ]
    lead_tasks = [
        task
        for task in data.get("tarefas", [])
        if not task.get("done") and task.get("vinculo_tipo") == "lead"
    ]
    stale_leads = [lead for lead in open_leads if is_stale_lead(lead)]
    overdue_sla = [lead for lead in open_leads if lead_sla_minutes_without_action(lead) > LEAD_FIRST_CONTACT_SLA_MINUTES]
    return {
        "new_budgets": len(budget_leads),
        "open_leads": len(open_leads),
        "lead_tasks": len(lead_tasks),
        "stale_leads": len(stale_leads),
        "overdue_sla": len(overdue_sla),
        "pipeline_total": sum(len(column["items"]) for column in pipeline["columns"]),
    }


def build_weekly_metrics(data):
    today = date.today()
    start = today - timedelta(days=today.weekday())
    leads_week = [lead for lead in data.get("leads", []) if (parse_datetime_iso(lead.get("created_at")) or datetime.min).date() >= start]
    lead_ids_week = {lead.get("id") for lead in leads_week}

    response_minutes = []
    for lead in leads_week:
        created = parse_datetime_iso(lead.get("created_at"))
        first_contact = parse_date(lead.get("ultima_interacao"))
        if created and first_contact and first_contact >= created.date():
            response_minutes.append(max(0, int((datetime.combine(first_contact, datetime.min.time()) - created).total_seconds() // 60)))

    proposal_count = 0
    for lead in data.get("leads", []):
        if lead.get("id") in lead_ids_week and lead_stage_key(lead) in ("proposal", "closed"):
            proposal_count += 1

    advance_rate = round((proposal_count / len(leads_week)) * 100, 1) if leads_week else 0.0
    avg_response = round(sum(response_minutes) / len(response_minutes), 1) if response_minutes else 0.0
    return {
        "week_label": f"{start.strftime('%d/%m')} a {today.strftime('%d/%m')}",
        "leads_week": len(leads_week),
        "avg_response_minutes": avg_response,
        "proposal_advance_rate": advance_rate,
    }


def build_dashboard_results(data, board):
    today = date.today()
    tasks_done = [task for task in data.get("tarefas", []) if parse_date(task.get("done_at")) == today]
    lead_done = [task for task in tasks_done if task.get("vinculo_tipo") == "lead"]
    contracts = [
        project
        for project in data.get("projetos", [])
        if parse_date((project.get("contrato") or {}).get("ultimo_followup_em")) == today
    ]
    clients = [
        client
        for client in data.get("clientes", [])
        if parse_date(client.get("ultima_interacao")) == today
    ]
    paid = []
    for project in data.get("projetos", []):
        for payment in project.get("pagamentos", []) or []:
            if parse_date(payment.get("pago_em")) == today:
                paid.append(payment)
    return {
        "tasks_done": len(tasks_done),
        "lead_done": len(lead_done),
        "contracts": len(contracts),
        "clients": len(clients),
        "paid": len(paid),
    }


def build_automation_actions(data, board):
    actions = []
    for task in (board["overdue"] + board["today"] + board["upcoming"]):
        if task.get("origem") == "automacao":
            has_whatsapp = task.get("whatsapp_url") and task.get("whatsapp_url") != "#"
            actions.append(
                {
                    "title": task.get("titulo"),
                    "subtitle": f"{task.get('contexto')} · {task.get('label')}",
                    "tone": "lead" if task.get("vinculo_tipo") == "lead" else "task",
                    "primary_label": "WhatsApp" if has_whatsapp else "Abrir",
                    "primary_url": task.get("whatsapp_url") if has_whatsapp else task.get("link_url") or url_for("tasks_page"),
                    "secondary_label": "Concluir",
                    "secondary_url": url_for("complete_task", task_id=task.get("id")),
                    "secondary_method": "post",
                }
            )
    for notification in build_notifications(data):
        if len(actions) >= 6:
            break
        actions.append(
            {
                "title": notification.get("title"),
                "subtitle": notification.get("subtitle"),
                "tone": (notification.get("category") or "").lower(),
                "primary_label": notification.get("action_label"),
                "primary_url": notification.get("action_url"),
                "secondary_label": notification.get("secondary_label"),
                "secondary_url": notification.get("secondary_url"),
                "secondary_method": "get",
            }
        )
    return actions[:6]


def quick_action(label, url, method="get", tone=""):
    return {"label": label, "url": url, "method": method, "tone": tone}


def smart_context_key(kind, item):
    for field in ("client_id", "cliente_id"):
        if item.get(field):
            return f"cliente:{item.get(field)}"
    if item.get("project_id"):
        return f"projeto:{item.get('project_id')}"
    if item.get("vinculo_tipo") and item.get("vinculo_id"):
        return f"{item.get('vinculo_tipo')}:{item.get('vinculo_id')}"
    if kind.startswith("lead") and item.get("id"):
        return f"lead:{item.get('id')}"
    if item.get("client_name"):
        return f"cliente_nome:{str(item.get('client_name')).lower()}"
    return ""


def smart_bucket(rank):
    if rank <= 15:
        return "Agora"
    if rank <= 55:
        return "Hoje"
    return "Depois"


def smart_action_rank(base, due_value=None, status="", priority=""):
    due = due_value if isinstance(due_value, date) else parse_date(due_value)
    delta = 999 if not due else (due - date.today()).days
    score = base
    if delta < 0:
        score -= 80 + min(abs(delta), 30)
    elif delta == 0:
        score -= 45
    elif delta <= 2:
        score -= 25
    elif delta <= 7:
        score -= 10
    if str(status).lower() in ("atrasado", "vencido"):
        score -= 35
    if str(priority).lower() == "alta":
        score -= 18
    elif str(priority).lower() == "baixa":
        score += 12
    return score


def build_daily_command(data, board):
    receivables = build_receivables(data)
    expenses = build_expenses(data)
    agenda = build_agenda_board(data)
    contract_actions = build_contract_actions(data)[:4]
    relationship = relationship_data(data)
    relationship_actions = []
    for client in relationship["birthdays_today"][:2]:
        relationship_actions.append(
            {
                "client_id": client.get("id"),
                "client_name": client.get("nome"),
                "title": f"Aniversário: {client.get('nome')}",
                "subtitle": "Enviar mensagem hoje.",
                "action_url": url_for("client_detail", client_id=client.get("id")),
                "whatsapp_url": whatsapp_link(client.get("tel"), f"Olá, {client.get('nome','').split(' ')[0]}! Feliz aniversário! Que seu novo ciclo seja muito especial."),
            }
        )
    for client in relationship["no_contact"][:3]:
        relationship_actions.append(
            {
                "client_id": client.get("id"),
                "client_name": client.get("nome"),
                "title": f"Retomar contato: {client.get('nome')}",
                "subtitle": f"{client.get('dias_sem_contato_label')} sem contato.",
                "action_url": url_for("client_detail", client_id=client.get("id")),
                "whatsapp_url": whatsapp_link(client.get("tel"), f"Olá, {client.get('nome','').split(' ')[0]}! Passando para saber como você está e se posso te ajudar em algo por aqui."),
            }
        )
    payment_actions = [
        item
        for item in receivables["items"]
        if item.get("status_calculado") in ("Atrasado", "Vence em breve")
    ][:4]
    expense_actions = [
        item
        for item in expenses["items"]
        if item.get("status_calculado") in ("Atrasado", "Vence em breve")
    ][:4]
    stale_leads = [
        lead
        for lead in data.get("leads", [])
        if is_stale_lead(lead) and lead_stage_key(lead) not in ("lost", "closed", "future")
    ][:4]
    todays_events = agenda["today"]
    critical_tasks = (board["overdue"] + board["today"])[:5]
    def days_until(value):
        due = value if isinstance(value, date) else parse_date(value)
        if not due:
            return 999
        return (due - date.today()).days

    def action_rank(kind, item=None, base=0):
        item = item or {}
        delta = days_until(item.get("due_date") or item.get("vencimento") or item.get("data") or item.get("prazo"))
        status = item.get("status_calculado") or item.get("status_label") or item.get("label") or ""
        if status == "Atrasado" or delta < 0:
            return base + max(delta, -30)
        if status in ("Vence em breve", "Hoje") or delta == 0:
            return base + 20 + max(delta, 0)
        return base + 60 + max(delta, 0)

    priority_actions = []
    for payment in payment_actions:
        status = payment.get("status_calculado")
        priority_actions.append(
            {
                "title": f"Cobrar {payment.get('client_name')}",
                "subtitle": f"{payment.get('valor_fmt')} · vence {payment.get('vencimento_fmt') or 'sem data'}",
                "tone": "payment",
                "label": status,
                "amount": payment.get("valor_fmt"),
                "url": url_for("receivables_page"),
                "action_label": "Pago",
                "action_url": url_for("mark_payment_paid", project_id=payment.get("project_id"), payment_id=payment.get("id")),
                "action_method": "post",
                "rank": action_rank("payment", payment, 0),
            }
        )
    for expense in expense_actions:
        status = expense.get("status_calculado")
        priority_actions.append(
            {
                "title": f"Pagar {expense.get('descricao')}",
                "subtitle": f"{expense.get('categoria') or 'Despesa'} · vence {expense.get('vencimento_fmt') or 'sem data'}",
                "tone": "expense",
                "label": status,
                "amount": expense.get("valor_fmt"),
                "url": url_for("finance_page", status=expense.get("status_calculado")),
                "action_label": "Pago",
                "action_url": url_for("mark_expense_paid", expense_id=expense.get("id")),
                "action_method": "post",
                "rank": action_rank("expense", expense, 10),
            }
        )
    for lead in stale_leads:
        lead_days = lead_days_since_interaction(lead)
        priority_actions.append(
            {
                "title": f"Follow-up com {lead.get('nome')}",
                "subtitle": f"{lead_days} dias sem avanço",
                "tone": "lead",
                "label": "Comercial",
                "amount": "",
                "url": url_for("leads"),
                "action_label": "Abrir",
                "action_url": url_for("leads"),
                "action_method": "get",
                "rank": 70 - min(lead_days, 30),
            }
        )
    for task in critical_tasks:
        due = parse_date(task.get("prazo"))
        priority_actions.append(
            {
                "title": task.get("titulo") or task.get("text"),
                "subtitle": f"{task.get('contexto')} · {task.get('label')}",
                "tone": "task",
                "label": "Tarefa",
                "amount": "",
                "url": task.get("link_url") or url_for("tasks_page"),
                "action_label": "Concluir",
                "action_url": url_for("complete_task", task_id=task.get("id")),
                "action_method": "post",
                "rank": action_rank("task", {"due_date": due, "status_label": task.get("label")}, 30),
            }
        )
    for event in todays_events[:3]:
        event_time = event.get("hora") or "23:59"
        time_rank = 0
        try:
            hour, minute = [int(part) for part in event_time.split(":")[:2]]
            time_rank = hour * 60 + minute
        except Exception:
            time_rank = 1439
        priority_actions.append(
            {
                "title": event.get("titulo") or "Compromisso",
                "subtitle": f"{event.get('hora') or 'sem horário'} · {event.get('context_label')}",
                "tone": "agenda",
                "label": "Agenda",
                "amount": "",
                "url": event.get("open_url") or url_for("agenda_page"),
                "action_label": "Concluir",
                "action_url": url_for("complete_event", event_id=event.get("id")),
                "action_method": "post",
                "rank": action_rank("agenda", event, 20) + (time_rank / 1440),
            }
        )
    for contract in contract_actions:
        priority_actions.append(
            {
                "title": f"Contrato pendente: {contract.get('client_name')}",
                "subtitle": f"{contract.get('project_name')} · {contract.get('status')}",
                "tone": "contract",
                "label": "Contrato",
                "amount": "",
                "url": contract.get("action_url") or url_for("projects"),
                "action_label": "Abrir",
                "action_url": contract.get("action_url") or url_for("projects"),
                "action_method": "get",
                "rank": 60,
            }
        )
    for item in relationship_actions:
        is_birthday = str(item.get("title") or "").startswith("Aniversário")
        priority_actions.append(
            {
                "title": item.get("title"),
                "subtitle": item.get("subtitle"),
                "tone": "relationship",
                "label": "Cliente",
                "amount": "",
                "url": item.get("action_url") or url_for("clients"),
                "action_label": "Abrir",
                "action_url": item.get("action_url") or url_for("clients"),
                "action_method": "get",
                "rank": 55 if is_birthday else 80,
            }
        )
    tone_order = {"payment": 0, "expense": 1, "agenda": 2, "task": 3, "lead": 4, "contract": 5, "relationship": 6}
    priority_actions = sorted(priority_actions, key=lambda item: (item.get("rank", 999), tone_order.get(item.get("tone"), 9)))
    return {
        "payment_actions": payment_actions,
        "expense_actions": expense_actions,
        "contract_actions": contract_actions,
        "relationship_actions": relationship_actions,
        "stale_leads": stale_leads,
        "critical_tasks": critical_tasks,
        "todays_events": todays_events,
        "priority_actions": priority_actions[:8],
        "counts": {
            "financeiro": len(payment_actions),
            "despesas": len(expense_actions),
            "comercial": len(stale_leads),
            "tarefas": len(critical_tasks),
            "agenda": len(todays_events),
            "contratos": len(contract_actions),
            "relacionamento": len(relationship_actions),
        },
    }


def build_smart_day_plan(data, board):
    base_command = build_daily_command(data, board)
    receivables = build_receivables(data)
    expenses = build_expenses(data)
    agenda = build_agenda_board(data)
    relationship = relationship_data(data)
    contract_actions = build_contract_actions(data)[:4]
    open_leads = [
        lead
        for lead in data.get("leads", [])
        if lead_stage_key(lead) not in ("lost", "closed", "future")
    ]
    new_leads = [
        lead
        for lead in open_leads
        if lead_stage_key(lead) == "new"
        and (lead.get("status") or "novo").lower() in ("novo", "ativo")
    ][:4]
    stale_leads = [lead for lead in open_leads if is_stale_lead(lead)][:4]
    payment_actions = [
        item
        for item in receivables["items"]
        if item.get("status_calculado") in ("Atrasado", "Vence em breve")
    ][:5]
    expense_actions = [
        item
        for item in expenses["items"]
        if item.get("status_calculado") in ("Atrasado", "Vence em breve")
    ][:4]
    critical_tasks = (board["overdue"] + board["today"])[:7]
    events = (agenda["overdue"] + agenda["today"])[:4]
    actions = []
    seen = set()
    context_seen = {}

    def add_action(key, item, context_key=""):
        if key in seen:
            return
        if context_key:
            count = context_seen.get(context_key, 0)
            if count >= 2:
                return
            context_seen[context_key] = count + 1
        seen.add(key)
        actions.append(item)

    for lead in new_leads:
        first_name = str(lead.get("nome") or "").split(" ")[0]
        whatsapp_url = whatsapp_link(lead.get("tel"), f"Olá, {first_name}! Recebi seu pedido e vou te chamar para entender melhor.")
        add_action(
            f"lead-new:{lead.get('id')}",
            {
                "title": f"Responder {lead.get('nome')}",
                "subtitle": f"{lead.get('origem') or 'Lead'} · {lead.get('ambiente') or 'interesse não informado'}",
                "reason": "Lead novo precisa virar conversa rápida.",
                "tone": "lead",
                "label": "Novo lead",
                "amount": "",
                "url": url_for("leads"),
                "action_label": "WhatsApp" if whatsapp_url != "#" else "Abrir",
                "action_url": whatsapp_url if whatsapp_url != "#" else url_for("leads"),
                "action_method": "get",
                "actions": [
                    quick_action("WhatsApp", whatsapp_url, "get", "primary") if whatsapp_url != "#" else quick_action("Abrir", url_for("leads"), "get", "primary"),
                    quick_action("Abrir", url_for("leads")),
                ],
                "rank": 5,
            },
            smart_context_key("lead-new", lead),
        )

    for payment in payment_actions:
        status = payment.get("status_calculado")
        add_action(
            f"payment:{payment.get('project_id')}:{payment.get('id')}",
            {
                "title": f"Cobrar {payment.get('client_name')}",
                "subtitle": f"{payment.get('valor_fmt')} · vence {payment.get('vencimento_fmt') or 'sem data'}",
                "reason": "Recebível precisa de atenção para não escapar do mês.",
                "tone": "payment",
                "label": status,
                "amount": payment.get("valor_fmt"),
                "url": url_for("receivables_page"),
                "action_label": "Pago",
                "action_url": url_for("mark_payment_paid", project_id=payment.get("project_id"), payment_id=payment.get("id")),
                "action_method": "post",
                "actions": [
                    quick_action("WhatsApp", payment.get("whatsapp_url"), "get", "primary") if payment.get("whatsapp_url") and payment.get("whatsapp_url") != "#" else quick_action("Abrir", url_for("receivables_page"), "get", "primary"),
                    quick_action("Pago", url_for("mark_payment_paid", project_id=payment.get("project_id"), payment_id=payment.get("id")), "post"),
                    quick_action("Abrir", url_for("receivables_page")),
                ],
                "rank": smart_action_rank(20, payment.get("due_date") or payment.get("vencimento"), status),
            },
            smart_context_key("payment", payment),
        )

    for expense in expense_actions:
        status = expense.get("status_calculado")
        add_action(
            f"expense:{expense.get('id')}",
            {
                "title": f"Pagar {expense.get('descricao')}",
                "subtitle": f"{expense.get('categoria') or 'Despesa'} · vence {expense.get('vencimento_fmt') or 'sem data'}",
                "reason": "Despesa aberta para manter o financeiro leve em dia.",
                "tone": "expense",
                "label": status,
                "amount": expense.get("valor_fmt"),
                "url": url_for("finance_page", status=expense.get("status_calculado")),
                "action_label": "Pago",
                "action_url": url_for("mark_expense_paid", expense_id=expense.get("id")),
                "action_method": "post",
                "actions": [
                    quick_action("Pago", url_for("mark_expense_paid", expense_id=expense.get("id")), "post", "primary"),
                    quick_action("Abrir", url_for("finance_page", status=expense.get("status_calculado"))),
                ],
                "rank": smart_action_rank(35, expense.get("due_date") or expense.get("vencimento"), status),
            },
        )

    for event in events:
        event_time = event.get("hora") or "23:59"
        try:
            hour, minute = [int(part) for part in event_time.split(":")[:2]]
            time_rank = (hour * 60 + minute) / 1440
        except Exception:
            time_rank = 1
        add_action(
            f"event:{event.get('id')}",
            {
                "title": event.get("titulo") or "Compromisso",
                "subtitle": f"{event.get('hora') or 'sem horário'} · {event.get('context_label')}",
                "reason": "Compromisso de hoje precisa estar na operação.",
                "tone": "agenda",
                "label": event.get("status_label") or "Agenda",
                "amount": "",
                "url": event.get("open_url") or url_for("agenda_page"),
                "action_label": "Concluir",
                "action_url": url_for("complete_event", event_id=event.get("id")),
                "action_method": "post",
                "actions": [
                    quick_action("Concluir", url_for("complete_event", event_id=event.get("id")), "post", "primary"),
                    quick_action("Abrir", event.get("open_url") or url_for("agenda_page")),
                ],
                "rank": smart_action_rank(30, event.get("data"), event.get("status_label")) + time_rank,
            },
            smart_context_key("event", event),
        )

    for task in critical_tasks:
        task_actions = []
        if task.get("whatsapp_url") and task.get("whatsapp_url") != "#":
            task_actions.append(quick_action("WhatsApp", task.get("whatsapp_url"), "get", "primary"))
        task_actions.extend(
            [
                quick_action("Concluir", url_for("complete_task", task_id=task.get("id")), "post", "primary" if not task_actions else ""),
                quick_action("Amanhã", url_for("postpone_task", task_id=task.get("id"), days=1), "post"),
                quick_action("Semana", url_for("postpone_task", task_id=task.get("id"), days=7), "post"),
                quick_action("Abrir", task.get("link_url") or url_for("tasks_page")),
            ]
        )
        add_action(
            f"task:{task.get('id')}",
            {
                "title": task.get("titulo") or task.get("text"),
                "subtitle": f"{task.get('contexto')} · {task.get('label')}",
                "reason": task.get("automation_reason") or "Tarefa aberta na fila operacional.",
                "tone": "task",
                "label": "Tarefa",
                "amount": "",
                "url": task.get("link_url") or url_for("tasks_page"),
                "action_label": "Concluir",
                "action_url": url_for("complete_task", task_id=task.get("id")),
                "action_method": "post",
                "actions": task_actions,
                "rank": smart_action_rank(45, task.get("prazo"), task.get("label"), task.get("pri")),
            },
            smart_context_key("task", task),
        )

    for lead in stale_leads:
        lead_days = lead_days_since_interaction(lead) or 0
        first_name = str(lead.get("nome") or "").split(" ")[0]
        whatsapp_url = whatsapp_link(lead.get("tel"), f"Olá, {first_name}! Passando para saber se você conseguiu avançar com calma. Posso te ajudar com o próximo passo?")
        add_action(
            f"lead-stale:{lead.get('id')}",
            {
                "title": f"Follow-up com {lead.get('nome')}",
                "subtitle": f"{lead_days} dias sem avanço",
                "reason": "Lead parado perde temperatura comercial.",
                "tone": "lead",
                "label": "Comercial",
                "amount": "",
                "url": url_for("leads"),
                "action_label": "WhatsApp" if whatsapp_url != "#" else "Abrir",
                "action_url": whatsapp_url if whatsapp_url != "#" else url_for("leads"),
                "action_method": "get",
                "actions": [
                    quick_action("WhatsApp", whatsapp_url, "get", "primary") if whatsapp_url != "#" else quick_action("Abrir", url_for("leads"), "get", "primary"),
                    quick_action("Abrir", url_for("leads")),
                ],
                "rank": 50 - min(lead_days, 30),
            },
            smart_context_key("lead-stale", lead),
        )

    for contract in contract_actions:
        add_action(
            f"contract:{contract.get('project_id')}",
            {
                "title": f"Contrato pendente: {contract.get('client_name')}",
                "subtitle": f"{contract.get('project_name')} · {contract.get('status')}",
                "reason": "Formalização parada trava o início ou a segurança do projeto.",
                "tone": "contract",
                "label": "Contrato",
                "amount": "",
                "url": contract.get("action_url") or url_for("projects"),
                "action_label": "Abrir",
                "action_url": contract.get("action_url") or url_for("projects"),
                "action_method": "get",
                "actions": [quick_action("Abrir", contract.get("action_url") or url_for("projects"), "get", "primary")],
                "rank": 58,
            },
            smart_context_key("contract", contract),
        )

    relationship_actions = []
    for client in relationship["birthdays_today"][:2]:
        relationship_actions.append((client, True))
    for client in relationship["no_contact"][:3]:
        relationship_actions.append((client, False))
    for client, is_birthday in relationship_actions:
        first_name = str(client.get("nome") or "").split(" ")[0]
        if is_birthday:
            title = f"Aniversário: {client.get('nome')}"
            subtitle = "Enviar mensagem hoje."
            message = f"Olá, {first_name}! Feliz aniversário! Que seu novo ciclo seja muito especial."
            rank = 60
        else:
            title = f"Retomar contato: {client.get('nome')}"
            subtitle = f"{client.get('dias_sem_contato_label')} sem contato."
            message = f"Olá, {first_name}! Passando para saber como você está e se posso te ajudar em algo por aqui."
            rank = 82
        whatsapp_url = whatsapp_link(client.get("tel"), message)
        add_action(
            f"relationship:{client.get('id')}:{is_birthday}",
            {
                "title": title,
                "subtitle": subtitle,
                "reason": "Relacionamento ativo mantém o cliente próximo da marca.",
                "tone": "relationship",
                "label": "Cliente",
                "amount": "",
                "url": url_for("client_detail", client_id=client.get("id")),
                "action_label": "WhatsApp" if whatsapp_url != "#" else "Abrir",
                "action_url": whatsapp_url if whatsapp_url != "#" else url_for("client_detail", client_id=client.get("id")),
                "action_method": "get",
                "actions": [
                    quick_action("WhatsApp", whatsapp_url, "get", "primary") if whatsapp_url != "#" else quick_action("Abrir", url_for("client_detail", client_id=client.get("id")), "get", "primary"),
                    quick_action("Abrir", url_for("client_detail", client_id=client.get("id"))),
                ],
                "rank": rank,
            },
            smart_context_key("relationship", client),
        )

    tone_order = {"payment": 0, "expense": 1, "lead": 2, "agenda": 3, "task": 4, "contract": 5, "relationship": 6}
    priority_actions = sorted(actions, key=lambda item: (item.get("rank", 999), tone_order.get(item.get("tone"), 9)))[:8]
    for item in priority_actions:
        item["bucket"] = smart_bucket(item.get("rank", 999))
    grouped_actions = []
    for label in ("Agora", "Hoje", "Depois"):
        items = [item for item in priority_actions if item.get("bucket") == label]
        if items:
            grouped_actions.append({"label": label, "actions": items})
    base_command["priority_actions"] = priority_actions
    base_command["next_action"] = priority_actions[0] if priority_actions else None
    base_command["grouped_actions"] = grouped_actions
    base_command["counts"]["comercial"] = len(new_leads) + len(stale_leads)
    base_command["counts"]["agenda"] = len(events)
    base_command["counts"]["tarefas"] = len(critical_tasks)
    return base_command


def enrich_clients(data):
    clients = []
    for client in data.get("clientes", []):
        item = dict(client)
        projects = [enrich_project(dict(p)) for p in data.get("projetos", []) if p.get("cliente_id") == client.get("id")]
        summary = payment_summary(projects)
        item["projetos"] = len(projects)
        item["financeiro"] = {
            "pending_count": summary["pending_count"],
            "open_total": money_to_float(summary["open_total_fmt"]),
            "open_total_fmt": summary["open_total_fmt"],
        }
        item["badge"] = client_snapshot(client, projects)["relationship_badge"]
        clients.append(item)
    return clients


def build_notifications(data):
    board = build_task_board(data)
    agenda = build_agenda_board(data)
    notifications = []
    dismissed = set(data.get("dismissed_notifications", []))
    instagram_leads = [
        lead
        for lead in data.get("leads", [])
        if (lead.get("origem") or "").lower() == "instagram"
        and (lead.get("etapa") or "").lower() == "orçamento recebido"
        and (lead.get("status") or "novo").lower() in ("novo", "ativo")
        and not has_open_automation_task(data, f"lead_response:{lead.get('id')}")
    ]
    for lead in instagram_leads[:4]:
        notifications.append(
            {
                "key": f"lead:{lead.get('id')}",
                "category": "Lead",
                "priority": 1,
                "title": f"Novo orçamento: {lead.get('nome')}",
                "subtitle": lead.get("ambiente") or "Pedido vindo do Instagram",
                "action_label": "Abrir leads",
                "action_url": url_for("leads"),
                "action_method": "get",
                "secondary_label": "WhatsApp",
                "secondary_url": whatsapp_link(lead.get("tel"), f"Olá, {str(lead.get('nome','')).split(' ')[0]}! Recebi seu pedido de orçamento e vou te chamar para entender melhor."),
            }
        )
    for task in board["overdue"][:4]:
        notifications.append(
            {
                "key": f"task:{task.get('id')}",
                "category": "Tarefa",
                "priority": 2,
                "title": task.get("titulo"),
                "subtitle": task.get("label"),
                "action_label": "Abrir tarefas",
                "action_url": url_for("tasks_page"),
                "action_method": "get",
                "secondary_label": "",
                "secondary_url": "",
            }
        )
    for task in board["today"][:4]:
        notifications.append(
            {
                "key": f"task:{task.get('id')}",
                "category": "Tarefa",
                "priority": 3,
                "title": task.get("titulo"),
                "subtitle": "Vence hoje",
                "action_label": "Abrir tarefas",
                "action_url": url_for("tasks_page"),
                "action_method": "get",
                "secondary_label": "",
                "secondary_url": "",
            }
        )
    for event in (agenda["overdue"] + agenda["today"])[:4]:
        notifications.append(
            {
                "key": f"event:{event.get('id')}:{event.get('status_label')}",
                "category": "Agenda",
                "priority": 2 if event.get("tone") == "overdue" else 3,
                "title": event.get("titulo") or "Compromisso",
                "subtitle": f"{event.get('status_label')} · {event.get('hora') or 'sem horário'} · {event.get('context_label')}",
                "action_label": "Abrir compromisso",
                "action_url": url_for("open_event", event_id=event.get("id")),
                "action_method": "get",
                "secondary_label": "",
                "secondary_url": "",
            }
        )
    for payment in build_receivables(data)["items"]:
        if payment.get("status_calculado") not in ("Atrasado", "Vence em breve"):
            continue
        notifications.append(
            {
                "key": f"payment:{payment.get('project_id')}:{payment.get('id')}:{payment.get('status_calculado')}",
                "category": "Pagamento",
                "priority": 1 if payment.get("status_calculado") == "Atrasado" else 2,
                "title": f"{payment.get('status_calculado')}: {payment.get('client_name')}",
                "subtitle": f"{payment.get('project_name')} · {payment.get('valor_fmt')} · {payment.get('vencimento_fmt') or 'sem vencimento'}",
                "action_label": "Abrir recebíveis",
                "action_url": url_for("receivables_page"),
                "action_method": "get",
                "secondary_label": "WhatsApp",
                "secondary_url": payment.get("whatsapp_url") or "",
            }
        )
        if len([n for n in notifications if n.get("category") == "Pagamento"]) >= 3:
            break
    for expense in build_expenses(data)["items"]:
        if expense.get("status_calculado") not in ("Atrasado", "Vence em breve"):
            continue
        notifications.append(
            {
                "key": f"expense:{expense.get('id')}:{expense.get('status_calculado')}",
                "category": "Despesa",
                "priority": 1 if expense.get("status_calculado") == "Atrasado" else 2,
                "title": f"{expense.get('status_calculado')}: {expense.get('descricao')}",
                "subtitle": f"{expense.get('categoria') or 'Despesa'} · {expense.get('valor_fmt')} · {expense.get('vencimento_fmt') or 'sem vencimento'}",
                "action_label": "Abrir financeiro",
                "action_url": url_for("finance_page", status=expense.get("status_calculado")),
                "action_method": "get",
                "secondary_label": "",
                "secondary_url": "",
            }
        )
        if len([n for n in notifications if n.get("category") == "Despesa"]) >= 3:
            break
    for contract in build_contract_actions(data)[:3]:
        notifications.append(
            {
                "key": f"contract:{contract.get('project_id')}",
                "category": "Contrato",
                "priority": 2,
                "title": f"Contrato pendente: {contract.get('client_name')}",
                "subtitle": f"{contract.get('project_name')} · {contract.get('status')}",
                "action_label": "Abrir projeto",
                "action_url": contract.get("action_url"),
                "action_method": "get",
                "secondary_label": "",
                "secondary_url": "",
            }
        )
    for client in relationship_data(data)["birthdays_today"][:2]:
        notifications.append(
            {
                "key": f"birthday:{client.get('id')}:{date.today().year}",
                "category": "Relacionamento",
                "priority": 3,
                "title": f"Aniversário: {client.get('nome')}",
                "subtitle": "Enviar uma mensagem hoje.",
                "action_label": "Abrir cliente",
                "action_url": url_for("client_detail", client_id=client.get("id")),
                "action_method": "get",
                "secondary_label": "",
                "secondary_url": "",
            }
        )
    for item in build_followups(data)[:3]:
        notifications.append(
            {
                "key": f"relationship:{item.get('client_id')}",
                "category": "Relacionamento",
                "priority": 4,
                "title": item.get("titulo") or item.get("title"),
                "subtitle": item.get("subtitle") or "",
                "action_label": item.get("action_label") or "Abrir",
                "action_url": item.get("action_url") or url_for("clients"),
                "action_method": item.get("action_method") or "get",
                "secondary_label": item.get("secondary_label") or "",
                "secondary_url": item.get("secondary_url") or "",
            }
        )
    visible = []
    for item in notifications:
        key = item.get("key") or item.get("title") or ""
        if key in dismissed:
            continue
        item["dismiss_url"] = url_for("dismiss_notification", key=key)
        visible.append(item)
    visible = sorted(visible, key=lambda item: (item.get("priority", 9), item.get("category") or ""))
    return visible[:8]


def notification_summary(notifications):
    summary = {"Comercial": 0, "Tarefa": 0, "Agenda": 0, "Pagamento": 0, "Despesa": 0, "Contrato": 0, "Relacionamento": 0}
    for item in notifications:
        category = item.get("category")
        if category == "Lead":
            category = "Comercial"
        if category in summary:
            summary[category] += 1
    return summary


def split_feedbacks(data):
    items = data.get("feedbacks", [])
    return {
        "all": items,
        "new": [i for i in items if i.get("status", "novo") == "novo"],
        "urgent": [i for i in items if i.get("urgencia") == "alta" and i.get("status") != "resolvido"],
        "planned": [i for i in items if i.get("status") in ("analisado", "planejado")],
        "resolved": [i for i in items if i.get("status") == "resolvido"],
    }


def feedback_report(feedbacks):
    open_items = [f for f in feedbacks if f.get("status") != "resolvido"]
    if not open_items:
        return "- Nenhum item registrado.\n\nElogios / pontos positivos:\n- Nenhum item registrado.\n\nContexto:\n- Total de feedbacks abertos: 0"
    lines = ["Feedbacks para ajustar no CRM:"]
    for item in open_items:
        lines.append(f"- {item.get('descricao')} ({item.get('tela')}, {item.get('data')})")
    lines.append("\nContexto:")
    lines.append(f"- Total de feedbacks abertos: {len(open_items)}")
    return "\n".join(lines)


def find_by_id(items, item_id):
    try:
        wanted = int(item_id)
    except (TypeError, ValueError):
        return None
    for item in items:
        if int(item.get("id", 0) or 0) == wanted:
            return item
    return None


@app.context_processor
def inject_globals():
    data = load_data()
    notifications = build_notifications(data)
    return {
        "nav_counts": nav_counts(data),
        "open_tasks_count": open_tasks_count(data),
        "brand_studio": current_brand(data),
        "notifications_menu": notifications,
        "notifications_count": len(notifications),
        "notifications_summary": notification_summary(notifications),
        "whatsapp_link": whatsapp_link,
        "mailto_link": mailto_link,
        "format_date_br": format_date_br,
    }


@app.route("/login", methods=["GET", "POST"])
def login():
    data = load_data()
    if request.method == "POST":
        login_value = (request.form.get("username") or "").strip().lower()
        password = request.form.get("password") or ""
        for user in data.get("users", []):
            valid_ids = [str(user.get("username", "")).lower(), str(user.get("email", "")).lower()]
            if login_value in valid_ids and password == str(user.get("password", "")):
                session["user"] = {"id": user["id"], "name": user.get("name") or user.get("username")}
                return redirect(url_for("dashboard"))
        flash("Login inválido.")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/notificacoes/<path:key>/dispensar", methods=["POST"])
@login_required
def dismiss_notification(key):
    data = load_data()
    dismissed = data.setdefault("dismissed_notifications", [])
    if key not in dismissed:
        dismissed.append(key)
    save_data(data)
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/notificacoes/<path:key>/abrir")
@login_required
def open_notification(key):
    data = load_data()
    dismissed = data.setdefault("dismissed_notifications", [])
    if key not in dismissed:
        dismissed.append(key)
        save_data(data)
    target = request.args.get("next") or url_for("dashboard")
    return redirect(target)


@app.route("/orcamento", methods=["GET", "POST"])
def public_budget_request():
    data = load_data()
    if request.method == "POST":
        name = (request.form.get("nome") or "").strip()
        phone = (request.form.get("telefone") or request.form.get("tel") or "").strip()
        if not name or not phone:
            flash("Informe nome e WhatsApp para enviar o orçamento.")
            return redirect(url_for("public_budget_request"))
        lead = {
            "id": next_id(data["leads"]),
            "nome": name,
            "tel": phone,
            "email": (request.form.get("email") or "").strip(),
            "profissao": "",
            "aniversario": "",
            "origem": "Instagram",
            "ambiente": request.form.get("ambiente") or request.form.get("interesse") or "",
            "orcamento": request.form.get("orcamento") or "",
            "prazo": request.form.get("prazo") or "",
            "obs": request.form.get("observacoes") or "",
            "ultima_interacao": today_br(),
            "etapa": "Orçamento recebido",
            "status": "Novo",
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        data["leads"].append(lead)
        create_lead_response_task(data, lead, "Responder orçamento recebido")
        register_operation_history(
            data,
            "Novo orçamento recebido",
            f"{lead.get('nome')} enviou pedido de orçamento pela página pública.",
            "lead",
            f"lead_budget:{lead.get('id')}",
            lead=lead,
            update_client=False,
        )
        save_data(data)
        return render_template("orcamento_obrigado.html", lead=lead)
    return render_template("orcamento.html")


@app.route("/health")
def health_check():
    return public_lead_response({"ok": True, "service": "uardon-crm"})


@app.route("/v1/leads", methods=["POST", "OPTIONS"])
def public_create_lead():
    if request.method == "OPTIONS":
        return public_lead_response({}, 204)

    raw_body = request.get_data(cache=True)
    signature_ok, signature_message = verify_public_lead_signature(raw_body)
    if not signature_ok:
        data = load_data()
        audit_public_lead(data, "landing_submit", "blocked", code="invalid_signature")
        save_data(data)
        return public_lead_error(signature_message, 401, "invalid_signature")

    origin = public_lead_origin()
    if request.headers.get("Origin") and not origin:
        data = load_data()
        audit_public_lead(data, "landing_submit", "blocked", code="origin_not_allowed")
        save_data(data)
        return public_lead_error("Origem não autorizada para enviar orçamento.", 403, "origin_not_allowed")

    ip = public_lead_client_ip()
    if public_lead_rate_limited(ip):
        data = load_data()
        audit_public_lead(data, "landing_submit", "blocked", code="rate_limited")
        save_data(data)
        return public_lead_error(
            "Muitas tentativas em pouco tempo. Aguarde alguns minutos e tente novamente.",
            429,
            "rate_limited",
        )

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return public_lead_error("Envio inválido. Revise os dados e tente novamente.")

    if str(payload.get("company_site") or "").strip():
        data = load_data()
        audit_public_lead(data, "landing_submit", "blocked", code="honeypot")
        save_data(data)
        return public_lead_error("Não foi possível enviar agora. Revise os dados e tente novamente.", 400, "blocked")

    name = clean_public_text(payload.get("name") or payload.get("nome") or "", 120)
    phone_raw = str(payload.get("phone") or payload.get("telefone") or payload.get("whatsapp") or "").strip()
    phone = normalize_brazil_phone(phone_raw)
    city = clean_public_text(payload.get("city") or payload.get("cidade") or "", 90)
    project_type = clean_public_text(payload.get("project_type") or payload.get("tipo") or "", 90)
    message = clean_public_text(payload.get("message") or payload.get("msg") or payload.get("observacoes") or "", 1000)

    if len(name) < 2:
        return public_lead_error("Digite seu nome para continuar.", 400, "invalid_name")
    if not is_valid_brazil_whatsapp(phone):
        return public_lead_error("WhatsApp inválido. Use um número real no formato (DDD) 9XXXX-XXXX.", 400, "invalid_phone")
    if not project_type:
        return public_lead_error("Selecione o tipo de projeto para continuar.", 400, "invalid_project_type")

    data = load_data()
    audit_public_lead(data, "landing_submit", "ok")
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    fingerprint = public_lead_fingerprint(phone, project_type, name)
    existing_lead = find_recent_public_lead(data, fingerprint)
    if existing_lead:
        audit_public_lead(data, "api_accept", "duplicate", lead=existing_lead, code="idempotent_replay")
        save_data(data)
        return public_lead_response(
            {"ok": True, "lead_id": existing_lead["id"], "status": existing_lead.get("status", "Novo"), "duplicate": True},
            200,
        )
    if public_lead_contact_rate_limited(phone):
        audit_public_lead(data, "landing_submit", "blocked", code="contact_rate_limited")
        save_data(data)
        return public_lead_error(
            "Muitas tentativas para este contato. Aguarde alguns minutos e tente novamente.",
            429,
            "contact_rate_limited",
        )

    turnstile_ok, turnstile_message, turnstile_error_code = verify_turnstile_token(
        str(payload.get("turnstile_token") or payload.get("cf_turnstile_response") or "").strip(),
        ip,
    )
    turnstile_warning = ""
    if not turnstile_ok:
        if not turnstile_fail_open_enabled():
            data = load_data()
            audit_public_lead(data, "landing_submit", "blocked", code="turnstile_failed")
            save_data(data)
            return public_lead_error(turnstile_message, 400, "turnstile_failed")
        turnstile_warning = f"Turnstile em modo tolerante. Motivo: {turnstile_error_code or 'unknown'}"

    created_at = datetime.now().isoformat(timespec="seconds")
    lead = {
        "id": next_id(data["leads"]),
        "nome": name,
        "tel": phone,
        "email": "",
        "profissao": "",
        "aniversario": "",
        "origem": "Landing Page",
        "cidade": city,
        "ambiente": project_type,
        "orcamento": "",
        "prazo": "",
        "obs": message,
        "ultima_interacao": today_br(),
        "etapa": "Novo",
        "status": "Novo",
        "responsavel": LEAD_OWNER_DEFAULT,
        "created_at": created_at,
        "primeiro_contato_prazo": lead_first_contact_deadline(created_at),
        "source_url": str(metadata.get("current_url") or "").strip(),
        "entry_page": str(metadata.get("entry_page") or metadata.get("current_url") or "").strip(),
        "referrer": str(metadata.get("referrer") or "").strip(),
        "utm_source": str(metadata.get("utm_source") or "").strip(),
        "utm_medium": str(metadata.get("utm_medium") or "").strip(),
        "utm_campaign": str(metadata.get("utm_campaign") or "").strip(),
        "utm_content": str(metadata.get("utm_content") or "").strip(),
        "utm_term": str(metadata.get("utm_term") or "").strip(),
        "idempotency_key": str(request.headers.get("Idempotency-Key") or payload.get("idempotency_key") or fingerprint).strip()[:160],
        "public_fingerprint": fingerprint,
    }
    if city or project_type or message:
        details = []
        if city:
            details.append(f"Cidade do projeto: {city}")
        if project_type:
            details.append(f"Tipo de projeto: {project_type}")
        if message:
            details.append(f"Mensagem: {message}")
        lead["obs"] = "\n".join(details)

    data["leads"].append(lead)
    audit_public_lead(data, "api_accept", "ok", lead=lead)
    create_lead_response_task(data, lead, "Responder lead da landing")
    register_operation_history(
        data,
        "Novo lead recebido pela landing",
        f"{lead.get('nome')} enviou pedido de orçamento pelo site uardon.com.br.",
        "lead",
        f"landing_lead:{lead.get('id')}",
        lead=lead,
        update_client=False,
    )
    audit_public_lead(data, "db_write", "ok", lead=lead)
    audit_public_lead(data, "crm_visible", "ok", lead=lead)
    save_data(data)
    return public_lead_response({"ok": True, "lead_id": lead["id"], "status": lead["status"]}, 201)


@app.route("/")
@login_required
def dashboard():
    data = load_data()
    if ensure_daily_automation_tasks(data):
        save_data(data)
    board = build_task_board(data)
    agenda = build_agenda_board(data)
    pipeline = build_lead_pipeline(data["leads"])
    commercial = build_commercial_metrics(data, board, pipeline)
    daily_command = build_smart_day_plan(data, board)
    events_today = agenda["today"]
    budget_leads = [
        lead
        for lead in data["leads"]
        if (lead.get("origem") or "").lower() == "instagram"
        and (lead.get("etapa") or "").lower() == "orçamento recebido"
    ][:5]
    summary = {
        "projects": len(data["projetos"]),
        "proposals": len(data["leads"]),
        "events_today": len(events_today),
        "tasks_today": len(board["today"]) + len(board["overdue"]),
        "ref_label": today_br(),
    }
    relationship = relationship_data(data)
    weekly_metrics = build_weekly_metrics(data)
    funnel = {"Atração": 0, "Interesse": 0, "Proposta": len(data["leads"]), "Negociação": 0, "Fechamento": 0}
    alerts = [{"title": n["title"], "subtitle": n["subtitle"]} for n in build_notifications(data)[:4]]
    return render_template(
        "dashboard.html",
        active="dashboard",
        summary=summary,
        tasks=(board["overdue"] + board["today"])[:8],
        events=events_today,
        followups=board["suggested"],
        alerts=alerts,
        projects=data["projetos"][:6],
        proposals=data["leads"][:5],
        budget_leads=budget_leads,
        commercial=commercial,
        daily_command=daily_command,
        dashboard_results=build_dashboard_results(data, board),
        pipeline=pipeline,
        automation_actions=build_automation_actions(data, board),
        relationship=relationship,
        weekly_metrics=weekly_metrics,
        funnel=funnel,
    )


@app.route("/atividades")
@login_required
def activities_page():
    data = load_data()
    filters = {
        "tipo": request.args.get("tipo") or "todos",
        "q": request.args.get("q") or "",
    }
    return render_template("activities.html", active="atividades", activities=build_activity_center(data, filters))


@app.route("/agenda")
@login_required
def agenda_page():
    data = load_data()
    agenda = build_agenda_board(data)
    calendar_month = build_calendar_month(agenda["all"], request.args.get("ano"), request.args.get("mes"))
    google_status = google_calendar_status()
    return render_template(
        "agenda.html",
        active="agenda",
        agenda=agenda,
        calendar_month=calendar_month,
        google_status=google_status,
        events=agenda["all"],
        clients=data["clientes"],
        projects=data["projetos"],
        event_types=EVENT_TYPES,
        meeting_types=MEETING_TYPES,
        task_types=TASK_TYPES,
        today_label=today_br(),
    )


@app.route("/agenda/novo", methods=["POST"])
@login_required
def create_event():
    data = load_data()
    client = find_by_id(data["clientes"], request.form.get("cliente_id"))
    project = find_by_id(data["projetos"], request.form.get("projeto_id"))
    event = {
        "id": next_id(data["eventos"]),
        "titulo": request.form.get("titulo") or "Novo compromisso",
        "tipo": request.form.get("tipo") or "Reunião",
        "data": request.form.get("data") or "",
        "hora": request.form.get("hora") or "",
        "hora_fim": request.form.get("hora_fim") or "",
        "cliente_id": client.get("id") if client else "",
        "cliente": client.get("nome") if client else "",
        "projeto_id": project.get("id") if project else "",
        "projeto": project.get("nome") if project else "",
        "reuniao_tipo": request.form.get("reuniao_tipo") or "",
        "link": request.form.get("link") or "",
        "local": request.form.get("local") or "",
        "observacoes": request.form.get("observacoes") or "",
        "status": "agendado",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    data["eventos"].append(event)
    if request.form.get("sync_google"):
        try:
            sync_event_to_google(event)
        except Exception as exc:
            event["google_sync_error"] = str(exc)
            flash(f"Compromisso criado no CRM, mas não sincronizou com Google Agenda: {exc}")
    save_data(data)
    flash("Compromisso criado.")
    return redirect(url_for("agenda_page"))


@app.route("/agenda/<int:event_id>/editar", methods=["POST"])
@login_required
def edit_event(event_id):
    data = load_data()
    event = find_by_id(data["eventos"], event_id)
    if not event:
        flash("Compromisso não encontrado.")
        return redirect(url_for("agenda_page"))
    client = find_by_id(data["clientes"], request.form.get("cliente_id"))
    project = find_by_id(data["projetos"], request.form.get("projeto_id"))
    event["titulo"] = request.form.get("titulo") or event.get("titulo") or "Compromisso"
    event["tipo"] = request.form.get("tipo") or event.get("tipo") or "Reunião"
    event["data"] = request.form.get("data") or event.get("data") or ""
    event["hora"] = request.form.get("hora") or ""
    event["hora_fim"] = request.form.get("hora_fim") or ""
    event["reuniao_tipo"] = request.form.get("reuniao_tipo") or ""
    event["link"] = request.form.get("link") or ""
    event["local"] = request.form.get("local") or ""
    event["observacoes"] = request.form.get("observacoes") or ""
    if project:
        event["projeto_id"] = project.get("id")
        event["projeto"] = project.get("nome")
        linked_client = find_by_id(data["clientes"], project.get("cliente_id"))
        if linked_client:
            event["cliente_id"] = linked_client.get("id")
            event["cliente"] = linked_client.get("nome")
        elif client:
            event["cliente_id"] = client.get("id")
            event["cliente"] = client.get("nome")
        else:
            event["cliente_id"] = ""
            event["cliente"] = ""
    elif client:
        event["cliente_id"] = client.get("id")
        event["cliente"] = client.get("nome")
        event["projeto_id"] = ""
        event["projeto"] = ""
    else:
        event["cliente_id"] = ""
        event["cliente"] = ""
        event["projeto_id"] = ""
        event["projeto"] = ""
    event["updated_at"] = datetime.now().isoformat(timespec="seconds")
    should_sync = request.form.get("sync_google") or event.get("google_event_id")
    if should_sync:
        try:
            sync_event_to_google(event)
        except Exception as exc:
            event["google_sync_error"] = str(exc)
            flash(f"Compromisso salvo no CRM, mas não atualizou no Google Agenda: {exc}")
    save_data(data)
    flash("Compromisso atualizado.")
    return redirect(request.referrer or url_for("agenda_page"))


@app.route("/agenda/<int:event_id>/acao", methods=["POST"])
@login_required
def create_event_action(event_id):
    data = load_data()
    event = find_by_id(data["eventos"], event_id)
    if not event:
        flash("Compromisso não encontrado.")
        return redirect(url_for("agenda_page"))
    title = request.form.get("titulo") or request.form.get("acao_tipo") or "Próxima ação"
    task = create_manual_event_action_task(
        data,
        event,
        title,
        request.form.get("tipo") or "Projeto",
        request.form.get("pri") or "Média",
        request.form.get("prazo") or "",
        request.form.get("descricao") or "",
    )
    save_data(data)
    flash(f"Ação criada em Tarefas: {task.get('titulo')}.")
    return redirect(request.referrer or url_for("agenda_page"))


@app.route("/agenda/google/conectar")
@login_required
def connect_google_calendar():
    try:
        flow = google_oauth_flow()
        authorization_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        session["google_oauth_state"] = state
        return redirect(authorization_url)
    except Exception as exc:
        flash(f"Não foi possível conectar o Google Agenda: {exc}")
        return redirect(url_for("agenda_page"))


@app.route("/agenda/google/callback")
@login_required
def google_calendar_callback():
    try:
        flow = google_oauth_flow()
        state = session.get("google_oauth_state")
        if state:
            flow.oauth2session.state = state
        flow.fetch_token(authorization_response=request.url)
        creds = flow.credentials
        google_calendar_paths()["token"].write_text(creds.to_json(), encoding="utf-8")
        session.pop("google_oauth_state", None)
        flash("Google Agenda conectado.")
    except Exception as exc:
        flash(f"Não foi possível finalizar a conexão com Google Agenda: {exc}")
    return redirect(url_for("agenda_page"))


@app.route("/agenda/<int:event_id>/google/sincronizar", methods=["POST"])
@login_required
def sync_google_event(event_id):
    data = load_data()
    event = find_by_id(data["eventos"], event_id)
    if not event:
        flash("Compromisso não encontrado.")
        return redirect(url_for("agenda_page"))
    try:
        sync_event_to_google(event)
        save_data(data)
        flash("Compromisso sincronizado com Google Agenda.")
    except Exception as exc:
        event["google_sync_error"] = str(exc)
        save_data(data)
        flash(f"Não foi possível sincronizar com Google Agenda: {exc}")
    return redirect(request.referrer or url_for("agenda_page"))


@app.route("/agenda/<int:event_id>/vincular", methods=["POST"])
@login_required
def link_event(event_id):
    data = load_data()
    event = find_by_id(data["eventos"], event_id)
    if not event:
        flash("Compromisso não encontrado.")
        return redirect(url_for("agenda_page"))
    client = find_by_id(data["clientes"], request.form.get("cliente_id"))
    project = find_by_id(data["projetos"], request.form.get("projeto_id"))
    apply_event_link(data, event, client, project)
    save_data(data)
    flash("Compromisso vinculado.")
    return redirect(request.referrer or url_for("agenda_page"))


@app.route("/agenda/<int:event_id>/confirmar-vinculo", methods=["POST"])
@login_required
def confirm_event_link_suggestion(event_id):
    data = load_data()
    event = find_by_id(data["eventos"], event_id)
    if not event:
        flash("Compromisso não encontrado.")
        return redirect(url_for("agenda_page"))
    suggestion = event_link_suggestion(event, data)
    if not suggestion:
        flash("Nenhuma sugestão segura de vínculo encontrada.")
        return redirect(request.referrer or url_for("agenda_page"))
    client = None
    project = None
    if suggestion.get("type") == "project":
        project = find_by_id(data["projetos"], suggestion.get("id"))
    elif suggestion.get("type") == "client":
        client = find_by_id(data["clientes"], suggestion.get("id"))
    apply_event_link(data, event, client, project)
    event["vinculo_sugerido_confirmado_em"] = today_br()
    event["vinculo_sugerido_confiança"] = suggestion.get("confidence", "")
    save_data(data)
    flash(f"Vínculo confirmado: {suggestion.get('label')}.")
    return redirect(request.referrer or url_for("agenda_page"))


@app.route("/agenda/google/importar", methods=["POST"])
@login_required
def import_google_calendar():
    data = load_data()
    try:
        result = import_google_events_to_crm(data)
        save_data(data)
        flash(f"Google Agenda importado: {result['created']} novo(s), {result['updated']} atualizado(s).")
    except Exception as exc:
        flash(f"Não foi possível importar do Google Agenda: {exc}")
    return redirect(url_for("agenda_page"))


@app.route("/agenda/<int:event_id>/abrir")
@login_required
def open_event(event_id):
    data = load_data()
    event = find_by_id(data["eventos"], event_id)
    if not event:
        flash("Compromisso não encontrado.")
        return redirect(url_for("agenda_page"))
    normalized = normalize_event(event, data)
    return redirect(normalized.get("open_url") or url_for("agenda_page", _anchor=f"evento-{event_id}"))


@app.route("/agenda/<int:event_id>/concluir", methods=["POST"])
@login_required
def complete_event(event_id):
    data = load_data()
    event = find_by_id(data["eventos"], event_id)
    if event:
        event["status"] = "concluido"
        event["concluido_em"] = today_br()
        register_completed_event_history(data, event)
        next_task = create_event_next_action_task(data, event)
        save_data(data)
        if next_task:
            flash("Compromisso concluído e próxima ação criada.")
        else:
            flash("Compromisso concluído.")
    return redirect(request.referrer or url_for("agenda_page"))


@app.route("/agenda/<int:event_id>/reabrir", methods=["POST"])
@login_required
def reopen_event(event_id):
    data = load_data()
    event = find_by_id(data["eventos"], event_id)
    if event:
        event["status"] = "agendado"
        event["concluido_em"] = ""
        save_data(data)
        flash("Compromisso reaberto.")
    return redirect(request.referrer or url_for("agenda_page"))


@app.route("/agenda/<int:event_id>/excluir", methods=["POST"])
@login_required
def delete_event(event_id):
    data = load_data()
    data["eventos"] = [e for e in data["eventos"] if int(e.get("id", 0)) != event_id]
    save_data(data)
    flash("Compromisso removido.")
    return redirect(url_for("agenda_page"))


@app.route("/modelos")
@login_required
def models_page():
    message_models = [
        {
            "title": "Primeiro contato",
            "category": "Comercial",
            "text": "Olá, [Nome]! Tudo bem? Sou a Vitória Uardon. Recebi seu contato e queria entender melhor o que você está imaginando para o seu espaço. Podemos marcar uma conversa rápida para eu te orientar sobre os próximos passos?",
        },
        {
            "title": "Follow-up de proposta",
            "category": "Comercial",
            "text": "Olá, [Nome]! Passando para saber se você conseguiu olhar a proposta com calma. Se tiver qualquer dúvida sobre escopo, prazos ou investimento, fico à disposição para te explicar tudo com tranquilidade.",
        },
        {
            "title": "Cobrança amigável",
            "category": "Financeiro",
            "text": "Olá, [Nome]! Passando para lembrar, com carinho, que a parcela de [descrição] do projeto [projeto] está prevista para [vencimento]. Qualquer dúvida, fico à disposição.",
        },
        {
            "title": "Assinatura de contrato",
            "category": "Contrato",
            "text": "Olá, [Nome]! Te enviei o contrato do projeto [projeto]. Assim que conseguir assinar, seguimos com a próxima etapa com tudo formalizado e organizado.",
        },
        {
            "title": "Pós-entrega",
            "category": "Relacionamento",
            "text": "Olá, [Nome]! Passando para saber como você está se sentindo com a entrega do projeto. Foi um prazer fazer parte dessa etapa e fico à disposição se precisar de algo.",
        },
        {
            "title": "Pedido de indicação",
            "category": "Relacionamento",
            "text": "Olá, [Nome]! Fiquei muito feliz em participar do seu projeto. Se você conhecer alguém que esteja pensando em transformar um ambiente, vou adorar receber essa indicação.",
        },
    ]
    checklist_models = [
        {
            "title": "Briefing e medição",
            "items": ["Confirmar ambientes do escopo", "Registrar medidas principais", "Entender rotina dos moradores", "Mapear referências e restrições", "Registrar prazo desejado e orçamento estimado"],
        },
        {
            "title": "Reunião de layout",
            "items": ["Apresentar distribuição dos ambientes", "Validar circulação e prioridades", "Registrar ajustes solicitados", "Confirmar decisões aprovadas", "Definir próxima entrega"],
        },
        {
            "title": "Apresentação do 3D",
            "items": ["Apresentar conceito visual", "Validar materiais e atmosfera", "Anotar alterações", "Confirmar pontos aprovados", "Agendar retorno ou próxima etapa"],
        },
        {
            "title": "Detalhamento de marcenaria",
            "items": ["Revisar medidas", "Conferir ferragens e soluções", "Registrar observações de execução", "Separar informações para fornecedores", "Validar pendências técnicas"],
        },
        {
            "title": "Entrega do caderno final",
            "items": ["Conferir pranchas finais", "Organizar links e arquivos", "Listar pendências restantes", "Enviar orientações ao cliente", "Registrar pós-entrega no histórico"],
        },
    ]
    return render_template("models.html", active="modelos", message_models=message_models, checklist_models=checklist_models)


@app.route("/clientes")
@login_required
def clients():
    data = load_data()
    return render_template("clients.html", active="clientes", clients=enrich_clients(data), relationship=relationship_data(data))


@app.route("/clientes/novo", methods=["POST"])
@login_required
def create_client():
    data = load_data()
    client = {
        "id": next_id(data["clientes"]),
        "nome": request.form.get("nome") or "",
        "tel": request.form.get("tel") or request.form.get("telefone") or "",
        "email": request.form.get("email") or "",
        "local": request.form.get("local") or request.form.get("cidade") or "",
        "projetos": 0,
        "valorTotal": 0,
        "indicacoes": 0,
        "status": "ativo",
        "obs": request.form.get("obs") or request.form.get("observacoes") or "",
        "historico": [],
    }
    data["clientes"].append(client)
    save_data(data)
    return redirect(url_for("clients"))


@app.route("/clientes/<int:client_id>")
@login_required
def client_detail(client_id):
    data = load_data()
    client = find_by_id(data["clientes"], client_id)
    if not client:
        return redirect(url_for("clients"))
    projects = [p for p in data["projetos"] if int(p.get("cliente_id", 0) or 0) == client_id]
    projects = [enrich_project(p) for p in projects]
    tasks = [normalize_task(t, data) for t in data["tarefas"] if int(t.get("cliente_id", 0) or 0) == client_id]
    snapshot = client_snapshot(client, projects)
    financeiro = payment_summary(projects)
    contracts = contracts_for_client(projects)
    first = client.get("nome", "").split(" ")[0]
    return render_template(
        "client_detail.html",
        active="clientes",
        client=client,
        projects=projects,
        tasks=tasks,
        snapshot=snapshot,
        financeiro=financeiro,
        contracts=contracts,
        timeline=build_client_timeline(client, projects, tasks, financeiro, contracts),
        next_action=client_next_action(client, snapshot, financeiro, contracts, tasks),
        followup_whatsapp=whatsapp_link(client.get("tel"), f"Olá, {first}! Passando para saber como você está e se posso te ajudar em algo por aqui."),
        birthday_whatsapp=whatsapp_link(client.get("tel"), f"Olá, {first}! Feliz aniversário! Que seu novo ciclo seja muito especial."),
        thanks_whatsapp=whatsapp_link(client.get("tel"), f"Olá, {first}! Obrigada pela confiança no nosso trabalho."),
    )


@app.route("/clientes/<int:client_id>/atualizar", methods=["POST"])
@login_required
def update_client(client_id):
    data = load_data()
    client = find_by_id(data["clientes"], client_id)
    if client:
        for key in ("nome", "tel", "email", "local", "obs", "profissao", "aniversario", "origem", "indicacao_por", "preferencia_contato", "status", "relacionamento_status", "ultima_interacao"):
            if key in request.form:
                client[key] = request.form.get(key)
        save_data(data)
    return redirect(url_for("client_detail", client_id=client_id))


@app.route("/clientes/<int:client_id>/interacao", methods=["POST"])
@login_required
def register_client_interaction(client_id):
    data = load_data()
    client = find_by_id(data["clientes"], client_id)
    if client:
        client.setdefault("historico", []).append({"data": today_br(), "titulo": request.form.get("titulo") or "Interação", "descricao": request.form.get("descricao") or ""})
        client["ultima_interacao"] = today_br()
        save_data(data)
    return redirect(url_for("client_detail", client_id=client_id))


@app.route("/clientes/<int:client_id>/contato-rapido", methods=["POST"])
@login_required
def quick_client_contact(client_id):
    data = load_data()
    client = find_by_id(data["clientes"], client_id)
    if client:
        client.setdefault("historico", []).append({"data": today_br(), "titulo": "Contato registrado", "descricao": "Contato rápido registrado pelo CRM."})
        client["ultima_interacao"] = today_br()
        save_data(data)
    return redirect(request.referrer or url_for("client_detail", client_id=client_id))


@app.route("/projetos")
@login_required
def projects():
    data = load_data()
    return render_template("projects.html", active="projetos", projects=[enrich_project(p) for p in data["projetos"]])


@app.route("/projetos/novo", methods=["POST"])
@login_required
def create_project():
    data = load_data()
    client = find_by_id(data["clientes"], request.form.get("cliente_id"))
    project = {
        "id": next_id(data["projetos"]),
        "nome": request.form.get("nome") or "",
        "cliente": client.get("nome") if client else request.form.get("cliente") or "",
        "cliente_id": client.get("id") if client else "",
        "valor": money_to_float(request.form.get("valor")),
        "prazo": request.form.get("prazo") or "",
        "tipo": request.form.get("tipo") or "",
        "progresso": 0,
        "status": "Planejamento",
        "obs": request.form.get("obs") or "",
        "etapas": [{"nome": name, "done": False, "data": ""} for name in PROJECT_STAGES],
        "arquivos": [],
        "contrato": {"status": "Não iniciado", "emitido_em": "", "assinado_em": "", "arquivo": None, "modelo": "Contrato padrão Vitória", "observacoes": "", "lembrete_assinatura_dias": 3, "ultimo_followup_em": ""},
        "pagamentos": [],
    }
    data["projetos"].append(project)
    save_data(data)
    return redirect(url_for("projects"))


@app.route("/clientes/<int:client_id>/projetos/novo", methods=["POST"])
@login_required
def create_project_for_client(client_id):
    data = load_data()
    client = find_by_id(data["clientes"], client_id)
    if not client:
        return redirect(url_for("client_detail", client_id=client_id))
    project = {
        "id": next_id(data["projetos"]),
        "nome": request.form.get("nome") or "",
        "cliente": client.get("nome"),
        "cliente_id": client.get("id"),
        "valor": money_to_float(request.form.get("valor")),
        "prazo": request.form.get("prazo") or "",
        "tipo": request.form.get("tipo") or "",
        "progresso": 0,
        "status": "Planejamento",
        "obs": request.form.get("obs") or "",
        "etapas": [{"nome": name, "done": False, "data": ""} for name in PROJECT_STAGES],
        "arquivos": [],
        "contrato": {"status": "Não iniciado", "emitido_em": "", "assinado_em": "", "arquivo": None, "modelo": "Contrato padrão Vitória", "observacoes": "", "lembrete_assinatura_dias": 3, "ultimo_followup_em": ""},
        "pagamentos": [],
    }
    data["projetos"].append(project)
    client["projetos"] = len([p for p in data["projetos"] if int(p.get("cliente_id", 0) or 0) == client_id])
    save_data(data)
    return redirect(url_for("client_detail", client_id=client_id))


@app.route("/projetos/<int:project_id>")
@login_required
def project_detail(project_id):
    data = load_data()
    if ensure_payment_ids(data):
        save_data(data)
    project = find_by_id(data["projetos"], project_id)
    if not project:
        return redirect(url_for("projects"))
    project = enrich_project(project)
    client = find_by_id(data["clientes"], project.get("cliente_id"))
    linked_tasks = [
        normalize_task(t, data)
        for t in data["tarefas"]
        if t.get("vinculo_tipo") == "projeto"
        and (str(t.get("vinculo_id")) == str(project_id) or str(t.get("vinculo_nome")) == str(project.get("nome")))
    ]
    categories = ["Drive / Links", "Briefing", "Imagens", "Executivo", "Contrato", "Entrega"]
    category_counts = {cat: len([f for f in project.get("arquivos", []) if f.get("categoria") == cat]) for cat in categories}
    contract_data = contract_label(project.get("contrato"))
    first = client.get("nome", "").split(" ")[0] if client else ""
    contract_data.update(
        {
            "whatsapp_url": whatsapp_link(client.get("tel") if client else "", f"Olá, {first}! Passando para lembrar da assinatura do contrato do projeto {project.get('nome')}."),
            "email_url": mailto_link(client.get("email") if client else "", f"Contrato - {project.get('nome')}", f"Olá, {first},\n\nPassando para lembrar da assinatura do contrato do projeto {project.get('nome')}.\n\nVitória Uardon"),
        }
    )
    payment_data = payment_summary([project])
    stage_data = project_stage_view(project)
    return render_template(
        "project_detail.html",
        active="projetos",
        project=project,
        clients=data["clientes"],
        client=client,
        linked_tasks=linked_tasks,
        file_categories=categories,
        category_counts=category_counts,
        payment_statuses=["Pendente", "Pago"],
        payment_data=payment_data,
        stage_data=stage_data,
        next_action=project_next_action(project, client, payment_data, contract_data, linked_tasks, stage_data),
        project_timeline=build_project_timeline(project, payment_data, linked_tasks),
        contract_statuses=["Não iniciado", "Enviado", "Em assinatura", "Assinado"],
        contract_data=contract_data,
    )


@app.route("/projetos/<int:project_id>/notas", methods=["POST"])
@login_required
def update_notes(project_id):
    data = load_data()
    project = find_by_id(data["projetos"], project_id)
    if project:
        project["obs"] = request.form.get("obs") or ""
        if "status" in request.form:
            project["status"] = request.form.get("status") or project.get("status") or ""
        if "prazo" in request.form:
            project["prazo"] = request.form.get("prazo") or ""
        save_data(data)
    return redirect(url_for("project_detail", project_id=project_id))


@app.route("/projetos/<int:project_id>/etapas/<int:stage_index>", methods=["POST"])
@app.route("/projetos/<int:project_id>/etapas/<int:index>", methods=["POST"])
@login_required
def toggle_stage(project_id, stage_index=None, index=None):
    stage_index = stage_index if stage_index is not None else index
    data = load_data()
    project = find_by_id(data["projetos"], project_id)
    if project and 0 <= stage_index < len(project.get("etapas", [])):
        stage = project["etapas"][stage_index]
        stage["done"] = not stage.get("done")
        stage["data"] = date.today().strftime("%d/%m") if stage["done"] else ""
        project["progresso"] = int(sum(1 for s in project["etapas"] if s.get("done")) / len(project["etapas"]) * 100)
        save_data(data)
    return redirect(url_for("project_detail", project_id=project_id))


@app.route("/tarefas")
@login_required
def tasks_page():
    data = load_data()
    if ensure_daily_automation_tasks(data):
        save_data(data)
    return render_template("tasks.html", active="tarefas", board=build_task_board(data), task_types=TASK_TYPES, clients=data["clientes"], projects=data["projetos"])


@app.route("/tarefas/nova", methods=["POST"])
@login_required
def create_task():
    data = load_data()
    client = find_by_id(data["clientes"], request.form.get("cliente_id"))
    project = find_by_id(data["projetos"], request.form.get("projeto_id"))
    vinculo_tipo = "projeto" if project else "cliente" if client else ""
    vinculo_id = project.get("id") if project else client.get("id") if client else ""
    vinculo_nome = project.get("nome") if project else client.get("nome") if client else ""
    linked_client_id = project.get("cliente_id") if project else client.get("id") if client else ""
    task = {
        "id": next_id(data["tarefas"]),
        "titulo": request.form.get("titulo") or "",
        "text": request.form.get("titulo") or "",
        "descricao": request.form.get("descricao") or "",
        "tipo": request.form.get("tipo") or "Interno",
        "pri": request.form.get("pri") or "Média",
        "prazo": request.form.get("prazo") or "",
        "done": False,
        "status": "Pendente",
        "responsavel": "Vitória Uardon",
        "vinculo_tipo": vinculo_tipo,
        "vinculo_id": vinculo_id,
        "vinculo_nome": vinculo_nome,
        "cliente_id": linked_client_id,
        "origem": "manual",
        "done_at": "",
    }
    data["tarefas"].append(task)
    save_data(data)
    return redirect(request.referrer or url_for("tasks_page"))


@app.route("/tarefas/<int:task_id>/concluir", methods=["POST"])
@login_required
def complete_task(task_id):
    data = load_data()
    task = find_by_id(data["tarefas"], task_id)
    if task:
        task["done"] = True
        task["status"] = "Concluída"
        task["done_at"] = today_br()
        complete_task_operational_effects(data, task)
        save_data(data)
    return redirect(request.referrer or url_for("tasks_page"))


@app.route("/tarefas/<int:task_id>/reabrir", methods=["POST"])
@login_required
def reopen_task(task_id):
    data = load_data()
    task = find_by_id(data["tarefas"], task_id)
    if task:
        task["done"] = False
        task["status"] = "Pendente"
        task["done_at"] = ""
        client, project, lead = task_history_targets(data, task)
        register_operation_history(
            data,
            "Tarefa reaberta",
            task.get("titulo") or task.get("text") or "Tarefa reaberta",
            "tarefa",
            f"task_reopen:{task_id}:{today_br()}",
            client=client,
            project=project,
            lead=lead,
            update_client=False,
        )
        save_data(data)
    return redirect(url_for("tasks_page"))


@app.route("/tarefas/<int:task_id>/adiar/<int:days>", methods=["POST"])
@login_required
def postpone_task(task_id, days):
    data = load_data()
    task = find_by_id(data["tarefas"], task_id)
    if task:
        base = parse_date(task.get("prazo")) or date.today()
        task["prazo"] = (base + timedelta(days=days)).isoformat()
        save_data(data)
    return redirect(request.referrer or url_for("tasks_page"))


@app.route("/tarefas/<int:task_id>/excluir", methods=["POST"])
@login_required
def delete_task(task_id):
    data = load_data()
    data["tarefas"] = [t for t in data["tarefas"] if int(t.get("id", 0)) != task_id]
    save_data(data)
    return redirect(url_for("tasks_page"))


@app.route("/leads")
@login_required
def leads():
    data = load_data()
    if ensure_daily_automation_tasks(data):
        save_data(data)
    leads_data = data["leads"]
    pipeline = build_lead_pipeline(leads_data)
    groups = {
        "active": [l for l in leads_data if (l.get("status") or "novo").lower() not in ("perdido", "futuro", "convertido")],
        "future": [l for l in leads_data if (l.get("status") or "").lower() == "futuro"],
        "lost": [l for l in leads_data if (l.get("status") or "").lower() == "perdido"],
    }
    return render_template("leads.html", active="leads", leads=leads_data, groups=groups, pipeline=pipeline, lead_loss_reasons=LEAD_LOSS_REASONS)


@app.route("/leads/novo", methods=["POST"])
@login_required
def create_lead():
    data = load_data()
    lead = {
        "id": next_id(data["leads"]),
        "nome": request.form.get("nome") or "",
        "tel": request.form.get("tel") or "",
        "email": request.form.get("email") or "",
        "profissao": request.form.get("profissao") or "",
        "origem": request.form.get("origem") or "",
        "ambiente": request.form.get("ambiente") or "",
        "orcamento": request.form.get("budget") or "",
        "obs": request.form.get("obs") or "",
        "ultima_interacao": today_br(),
        "status": "Novo",
        "responsavel": LEAD_OWNER_DEFAULT,
        "etapa": request.form.get("etapa") or "Atração",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "primeiro_contato_prazo": lead_first_contact_deadline(datetime.now().isoformat(timespec="seconds")),
    }
    data["leads"].append(lead)
    create_lead_response_task(data, lead, "Responder lead")
    save_data(data)
    return redirect(url_for("leads"))


@app.route("/leads/<int:lead_id>/contato", methods=["POST"])
@login_required
def mark_lead_contacted(lead_id):
    data = load_data()
    lead = find_by_id(data["leads"], lead_id)
    if lead:
        lead["status"] = "Em contato"
        lead["etapa"] = "Contato feito"
        lead["ultima_interacao"] = today_br()
        register_operation_history(
            data,
            "Lead em contato",
            f"Primeiro contato registrado para {lead.get('nome')}.",
            "lead",
            f"lead_contacted:{lead_id}:{today_br()}",
            lead=lead,
        )
        complete_lead_automation_tasks(data, lead_id, ["lead_response"])
        save_data(data)
    return redirect(url_for("leads"))


@app.route("/leads/<int:lead_id>/etapa/<stage>", methods=["POST"])
@login_required
def update_lead_stage(lead_id, stage):
    stages = {
        "novo": ("Novo", "Orçamento recebido"),
        "contato": ("Em contato", "Contato feito"),
        "briefing": ("Em contato", "Briefing marcado"),
        "proposta": ("Em contato", "Proposta enviada"),
        "fechado": ("convertido", "Convertido em cliente"),
    }
    if stage not in stages:
        return redirect(url_for("leads"))
    if stage == "fechado":
        return convert_lead(lead_id)
    data = load_data()
    lead = find_by_id(data["leads"], lead_id)
    if lead:
        lead["status"], lead["etapa"] = stages[stage]
        lead["ultima_interacao"] = today_br()
        register_operation_history(
            data,
            "Lead mudou de etapa",
            f"{lead.get('nome')} foi movido para {lead.get('etapa')}.",
            "lead",
            f"lead_stage:{lead_id}:{stage}:{today_br()}",
            lead=lead,
        )
        if stage != "novo":
            complete_lead_automation_tasks(data, lead_id, ["lead_response"])
        if stage in ("fechado", "futuro"):
            complete_lead_automation_tasks(data, lead_id, ["lead_followup"])
        save_data(data)
    return redirect(url_for("leads"))


@app.route("/leads/<int:lead_id>/converter", methods=["POST"])
@login_required
def convert_lead(lead_id):
    data = load_data()
    lead = find_by_id(data["leads"], lead_id)
    if lead:
        existing = next(
            (
                client
                for client in data["clientes"]
                if (lead.get("tel") and client.get("tel") == lead.get("tel"))
                or (lead.get("email") and client.get("email") == lead.get("email"))
            ),
            None,
        )
        client = existing
        if not client:
            client = {
                "id": next_id(data["clientes"]),
                "nome": lead.get("nome") or "",
                "tel": lead.get("tel") or "",
                "email": lead.get("email") or "",
                "profissao": lead.get("profissao") or "",
                "aniversario": lead.get("aniversario") or "",
                "cidade": "",
                "origem": lead.get("origem") or "",
                "obs": lead.get("obs") or "",
                "quem_indicou": "",
                "preferencia_contato": "WhatsApp",
                "relacionamento_status": "ativo",
                "ultima_interacao": today_br(),
            }
            data["clientes"].append(client)
        lead["status"] = "convertido"
        lead["etapa"] = "Convertido em cliente"
        lead["convertido_em"] = today_br()
        register_operation_history(
            data,
            "Lead convertido em cliente",
            f"{lead.get('nome')} entrou na base de clientes.",
            "lead",
            f"lead_converted:{lead_id}:{lead.get('convertido_em')}",
            client=client,
            lead=lead,
        )
        for task in data.get("tarefas", []):
            if task.get("automation_key") == f"lead_response:{lead_id}" and not task.get("done"):
                task["done"] = True
                task["status"] = "Concluída"
                task["done_at"] = today_br()
            if task.get("automation_key") == f"lead_followup:{lead_id}" and not task.get("done"):
                task["done"] = True
                task["status"] = "Concluída"
                task["done_at"] = today_br()
        save_data(data)
    return redirect(url_for("leads"))


@app.route("/leads/<int:lead_id>/reativar", methods=["POST"])
@login_required
def reactivate_lead(lead_id):
    data = load_data()
    lead = find_by_id(data["leads"], lead_id)
    if lead:
        lead["status"] = "Novo"
        lead["etapa"] = "Contato retomado"
        lead["ultima_interacao"] = today_br()
        lead["perda_motivo"] = ""
        register_operation_history(
            data,
            "Lead reativado",
            f"{lead.get('nome')} voltou para atendimento ativo.",
            "lead",
            f"lead_reactivated:{lead_id}:{today_br()}",
            lead=lead,
        )
        create_lead_response_task(data, lead, "Responder lead reativado")
        save_data(data)
    return redirect(url_for("leads"))


@app.route("/leads/<int:lead_id>/perdido", methods=["POST"])
@login_required
def mark_lead_lost(lead_id):
    data = load_data()
    lead = find_by_id(data["leads"], lead_id)
    if lead:
        lead["status"] = "perdido"
        lead["etapa"] = "Perdido"
        lead["perda_motivo"] = request.form.get("perda_motivo") or "Outro"
        lead["perda_obs"] = request.form.get("perda_obs") or ""
        lead["perdido_em"] = today_br()
        description = f"Motivo: {lead.get('perda_motivo')}."
        if lead.get("perda_obs"):
            description += f" Observação: {lead.get('perda_obs')}"
        register_operation_history(
            data,
            "Lead marcado como perdido",
            description,
            "lead",
            f"lead_lost:{lead_id}:{lead.get('perdido_em')}",
            lead=lead,
        )
        for task in data.get("tarefas", []):
            if task.get("automation_key") == f"lead_response:{lead_id}" and not task.get("done"):
                task["done"] = True
                task["status"] = "Concluída"
                task["done_at"] = today_br()
            if task.get("automation_key") == f"lead_followup:{lead_id}" and not task.get("done"):
                task["done"] = True
                task["status"] = "Concluída"
                task["done_at"] = today_br()
        save_data(data)
    return redirect(url_for("leads"))


@app.route("/leads/<int:lead_id>/futuro", methods=["POST"])
@login_required
def mark_lead_future(lead_id):
    data = load_data()
    lead = find_by_id(data["leads"], lead_id)
    if lead:
        lead["status"] = "futuro"
        lead["etapa"] = "Nutrição futura"
        lead["futuro_retorno"] = request.form.get("futuro_retorno") or ""
        lead["perda_obs"] = request.form.get("perda_obs") or ""
        description = "Lead movido para nutrição futura."
        if lead.get("futuro_retorno"):
            description += f" Retomar em: {lead.get('futuro_retorno')}."
        if lead.get("perda_obs"):
            description += f" Observação: {lead.get('perda_obs')}"
        register_operation_history(
            data,
            "Lead movido para futuro",
            description,
            "lead",
            f"lead_future:{lead_id}:{today_br()}",
            lead=lead,
        )
        for task in data.get("tarefas", []):
            if task.get("automation_key") == f"lead_response:{lead_id}" and not task.get("done"):
                task["done"] = True
                task["status"] = "Concluída"
                task["done_at"] = today_br()
            if task.get("automation_key") == f"lead_followup:{lead_id}" and not task.get("done"):
                task["done"] = True
                task["status"] = "Concluída"
                task["done_at"] = today_br()
        save_data(data)
    return redirect(url_for("leads"))


@app.route("/feedbacks")
@login_required
def feedbacks_page():
    data = load_data()
    return render_template("feedbacks.html", active="feedbacks", feedbacks=split_feedbacks(data), report=feedback_report(data["feedbacks"]))


@app.route("/feedbacks/novo", methods=["POST"])
@login_required
def create_feedback():
    data = load_data()
    data["feedbacks"].append({"id": next_id(data["feedbacks"]), "tipo": request.form.get("tipo") or "melhoria", "tela": request.form.get("tela") or "", "descricao": request.form.get("descricao") or "", "urgencia": request.form.get("urgencia") or "media", "status": "novo", "data": today_br(), "created_at": datetime.now().isoformat(timespec="seconds")})
    save_data(data)
    return redirect(url_for("feedbacks_page"))


@app.route("/feedbacks/<int:feedback_id>/status", methods=["POST"])
@login_required
def update_feedback_status(feedback_id):
    data = load_data()
    item = find_by_id(data["feedbacks"], feedback_id)
    if item:
        item["status"] = request.form.get("status") or "novo"
        if item["status"] == "resolvido":
            item["resolvido_em"] = today_br()
        save_data(data)
    return redirect(url_for("feedbacks_page"))


@app.route("/feedbacks/<int:feedback_id>/excluir", methods=["POST"])
@login_required
def delete_feedback(feedback_id):
    data = load_data()
    data["feedbacks"] = [f for f in data["feedbacks"] if int(f.get("id", 0)) != feedback_id]
    save_data(data)
    return redirect(url_for("feedbacks_page"))


@app.route("/feedbacks/resolver-todos", methods=["POST"])
@login_required
def resolve_all_feedbacks():
    data = load_data()
    for item in data["feedbacks"]:
        if item.get("status") != "resolvido":
            item["status"] = "resolvido"
            item["resolvido_em"] = today_br()
    save_data(data)
    return redirect(url_for("feedbacks_page"))


@app.route("/feedbacks/limpar-resolvidos", methods=["POST"])
@login_required
def clear_resolved_feedbacks():
    data = load_data()
    data["feedbacks"] = [f for f in data["feedbacks"] if f.get("status") != "resolvido"]
    save_data(data)
    return redirect(url_for("feedbacks_page"))


@app.route("/importar/<kind>")
@login_required
def import_csv_page(kind):
    return render_template("import_csv.html", active=kind, kind=kind, label="clientes" if kind == "clientes" else "leads", preview=None)


@app.route("/importar/<kind>", methods=["POST"])
@login_required
def confirm_import_csv(kind):
    return redirect(url_for("import_csv_page", kind=kind))


@app.route("/importar/modelo/<kind>.csv")
@login_required
def download_import_model(kind):
    headers = ["nome", "telefone", "e-mail", "profissão", "aniversário", "cidade", "origem", "observações"]
    if kind == "leads":
        headers = ["nome", "telefone", "e-mail", "profissão", "aniversário", "origem", "ambiente/interesse", "orçamento", "observações", "última interação", "etapa", "status"]
    output = ",".join(headers) + "\n"
    return Response(output, mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename=modelo_importacao_{kind}.csv"})


@app.route("/projetos/<int:project_id>/pagamentos/novo", methods=["POST"])
@login_required
def add_project_payment(project_id):
    data = load_data()
    project = find_by_id(data["projetos"], project_id)
    if project:
        append_project_payment(project, request.form)
        save_data(data)
        flash("Parcela adicionada.")
    return redirect(request.referrer or url_for("project_detail", project_id=project_id))


@app.route("/projetos/<int:project_id>/pagamentos/<int:payment_id>/pago", methods=["POST"])
@login_required
def mark_payment_paid(project_id, payment_id):
    data = load_data()
    project = find_by_id(data["projetos"], project_id)
    payment = find_by_id(project.get("pagamentos", []) if project else [], payment_id)
    if payment:
        payment["status"] = "Pago"
        payment["pago"] = True
        payment["pago_em"] = today_br()
        client = find_by_id(data.get("clientes", []), project.get("cliente_id")) if project else None
        register_operation_history(
            data,
            "Parcela marcada como paga",
            f"{payment.get('descricao') or 'Parcela'} · {format_money(money_to_float(payment.get('valor')))}",
            "recebivel",
            f"payment_paid:{project_id}:{payment_id}:{payment.get('pago_em')}",
            client=client,
            project=project,
            update_client=False,
        )
        save_data(data)
        flash("Parcela marcada como paga.")
    return redirect(request.referrer or url_for("project_detail", project_id=project_id))


@app.route("/projetos/<int:project_id>/pagamentos/<int:payment_id>/pendente", methods=["POST"])
@login_required
def mark_payment_pending(project_id, payment_id):
    data = load_data()
    project = find_by_id(data["projetos"], project_id)
    payment = find_by_id(project.get("pagamentos", []) if project else [], payment_id)
    if payment:
        payment["status"] = "Pendente"
        payment["pago"] = False
        payment["pago_em"] = ""
        client = find_by_id(data.get("clientes", []), project.get("cliente_id")) if project else None
        register_operation_history(
            data,
            "Parcela reaberta",
            f"{payment.get('descricao') or 'Parcela'} voltou para pendente.",
            "recebivel",
            f"payment_pending:{project_id}:{payment_id}:{today_br()}",
            client=client,
            project=project,
            update_client=False,
        )
        save_data(data)
        flash("Parcela voltou para pendente.")
    return redirect(request.referrer or url_for("project_detail", project_id=project_id))


@app.route("/projetos/<int:project_id>/pagamentos/<int:payment_id>/lembrado", methods=["POST"])
@login_required
def mark_payment_reminded(project_id, payment_id):
    data = load_data()
    project = find_by_id(data["projetos"], project_id)
    payment = find_by_id(project.get("pagamentos", []) if project else [], payment_id)
    if payment:
        payment["ultimo_lembrete_em"] = today_br()
        client = find_by_id(data.get("clientes", []), project.get("cliente_id")) if project else None
        register_operation_history(
            data,
            "Lembrete de cobrança enviado",
            f"{payment.get('descricao') or 'Parcela'} · vence {format_date_br(payment.get('vencimento')) or 'sem data'}.",
            "recebivel",
            f"payment_reminded:{project_id}:{payment_id}:{payment.get('ultimo_lembrete_em')}",
            client=client,
            project=project,
            update_client=False,
        )
        save_data(data)
        flash("Lembrete registrado.")
    return redirect(request.referrer or url_for("project_detail", project_id=project_id))


@app.route("/projetos/<int:project_id>/pagamentos/<int:payment_id>/excluir", methods=["POST"])
@login_required
def delete_payment(project_id, payment_id):
    data = load_data()
    project = find_by_id(data["projetos"], project_id)
    if project:
        project["pagamentos"] = [p for p in project.get("pagamentos", []) if int(p.get("id", 0) or 0) != payment_id]
        save_data(data)
        flash("Parcela removida.")
    return redirect(request.referrer or url_for("project_detail", project_id=project_id))


@app.route("/recebiveis")
@login_required
def receivables_page():
    data = load_data()
    if ensure_payment_ids(data):
        save_data(data)
    filters = {
        "status": request.args.get("status") or "todos",
        "mes": request.args.get("mes") or "",
        "q": request.args.get("q") or "",
    }
    receivables = build_receivables(data, filters)
    return render_template("receivables.html", active="recebiveis", receivables=receivables, projects=data["projetos"])


@app.route("/financeiro")
@login_required
def finance_page():
    data = load_data()
    if ensure_payment_ids(data):
        save_data(data)
    filters = {
        "status": request.args.get("status") or "todos",
        "mes": request.args.get("mes") or date.today().strftime("%Y-%m"),
        "q": request.args.get("q") or "",
    }
    finance = build_financial(data, filters)
    return render_template("finance.html", active="financeiro", finance=finance, expense_categories=EXPENSE_CATEGORIES)


@app.route("/financeiro/despesas/novo", methods=["POST"])
@login_required
def create_expense():
    data = load_data()
    expense = {
        "id": next_id(data.setdefault("despesas", [])),
        "descricao": request.form.get("descricao") or "Despesa",
        "categoria": request.form.get("categoria") or "Outro",
        "valor": request.form.get("valor") or 0,
        "vencimento": request.form.get("vencimento") or "",
        "status": request.form.get("status") or "Pendente",
        "pago": (request.form.get("status") or "Pendente") == "Pago",
        "pago_em": today_br() if (request.form.get("status") or "Pendente") == "Pago" else "",
        "recorrente": bool(request.form.get("recorrente")),
        "observacoes": request.form.get("observacoes") or "",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    data["despesas"].append(expense)
    save_data(data)
    flash("Despesa adicionada.")
    return redirect(url_for("finance_page", mes=(parse_date(expense.get("vencimento")) or date.today()).strftime("%Y-%m")))


@app.route("/financeiro/despesas/<int:expense_id>/pago", methods=["POST"])
@login_required
def mark_expense_paid(expense_id):
    data = load_data()
    expense = find_by_id(data.get("despesas", []), expense_id)
    if expense:
        expense["status"] = "Pago"
        expense["pago"] = True
        expense["pago_em"] = today_br()
        save_data(data)
        flash("Despesa marcada como paga.")
    return redirect(request.referrer or url_for("finance_page"))


@app.route("/financeiro/despesas/<int:expense_id>/pendente", methods=["POST"])
@login_required
def mark_expense_pending(expense_id):
    data = load_data()
    expense = find_by_id(data.get("despesas", []), expense_id)
    if expense:
        expense["status"] = "Pendente"
        expense["pago"] = False
        expense["pago_em"] = ""
        save_data(data)
        flash("Despesa voltou para pendente.")
    return redirect(request.referrer or url_for("finance_page"))


@app.route("/financeiro/despesas/<int:expense_id>/excluir", methods=["POST"])
@login_required
def delete_expense(expense_id):
    data = load_data()
    data["despesas"] = [expense for expense in data.get("despesas", []) if int(expense.get("id", 0) or 0) != expense_id]
    save_data(data)
    flash("Despesa removida.")
    return redirect(request.referrer or url_for("finance_page"))


@app.route("/recebiveis/parcelas/novo", methods=["POST"])
@login_required
def create_receivable_payment():
    data = load_data()
    project = find_by_id(data["projetos"], request.form.get("project_id"))
    if project:
        append_project_payment(project, request.form)
        save_data(data)
        flash("Parcela adicionada em Recebíveis.")
    else:
        flash("Selecione um projeto para criar a parcela.")
    return redirect(url_for("receivables_page"))


@app.route("/projetos/<int:project_id>/contrato", methods=["POST"])
@login_required
def update_contract(project_id):
    data = load_data()
    project = find_by_id(data["projetos"], project_id)
    if project:
        contract = project.setdefault("contrato", {})
        old_status = contract.get("status")
        for key in ("status", "modelo", "emitido_em", "assinado_em", "lembrete_assinatura_dias", "observacoes"):
            if key in request.form:
                contract[key] = request.form.get(key) or ""
        if contract.get("status") == "Assinado" and not contract.get("assinado_em"):
            contract["assinado_em"] = today_br()
        if old_status != contract.get("status"):
            contract["status_atualizado_em"] = today_br()
            client = find_by_id(data.get("clientes", []), project.get("cliente_id"))
            register_operation_history(
                data,
                "Contrato atualizado",
                f"{project.get('nome')} · {old_status or 'sem status'}  {contract.get('status') or 'sem status'}",
                "contrato",
                f"contract_status:{project_id}:{contract.get('status')}:{contract.get('status_atualizado_em')}",
                client=client,
                project=project,
                update_client=False,
            )
        file = request.files.get("arquivo")
        if file and file.filename:
            project_dir = UPLOAD_DIR / f"projeto_{project_id}"
            project_dir.mkdir(parents=True, exist_ok=True)
            safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", file.filename)
            filename = f"contrato_{datetime.now():%Y%m%d_%H%M%S}_{safe_name}"
            file.save(project_dir / filename)
            contract["arquivo"] = {"filename": filename, "original_name": file.filename, "uploaded_at": today_br()}
        save_data(data)
    return redirect(url_for("project_detail", project_id=project_id))


@app.route("/projetos/<int:project_id>/contrato/followup", methods=["POST"])
@login_required
def contract_followup(project_id):
    data = load_data()
    project = find_by_id(data["projetos"], project_id)
    if project:
        contract = project.setdefault("contrato", {})
        contract["ultimo_followup_em"] = today_br()
        client = find_by_id(data.get("clientes", []), project.get("cliente_id"))
        register_operation_history(
            data,
            "Follow-up de contrato",
            f"Lembrete de assinatura registrado para {project.get('nome')}.",
            "contrato",
            f"contract_followup:{project_id}:{contract.get('ultimo_followup_em')}",
            client=client,
            project=project,
            update_client=False,
        )
        save_data(data)
    return redirect(url_for("project_detail", project_id=project_id))


@app.route("/projetos/<int:project_id>/arquivos/<path:filename>")
@login_required
def serve_project_file(project_id, filename):
    return send_file(UPLOAD_DIR / f"projeto_{project_id}" / filename)


@app.route("/projetos/<int:project_id>/contrato/arquivo/<path:filename>")
@login_required
def serve_contract_file(project_id, filename):
    return send_file(UPLOAD_DIR / f"projeto_{project_id}" / filename)


@app.route("/projetos/<int:project_id>/arquivos", methods=["POST"])
@login_required
def upload_project_file(project_id):
    data = load_data()
    project = find_by_id(data["projetos"], project_id)
    if not project:
        return redirect(url_for("projects"))
    link = request.form.get("link") or request.form.get("url") or ""
    title = request.form.get("titulo") or request.form.get("nome") or link or "Link do projeto"
    if link:
        project.setdefault("arquivos", []).append({"id": next_id(project.get("arquivos", [])), "tipo": "link", "title": title, "url": link, "filename": "", "original_name": title, "created_at": today_br()})
        save_data(data)
    return redirect(url_for("project_detail", project_id=project_id))


@app.route("/projetos/<int:project_id>/arquivos/<int:file_id>/excluir", methods=["POST"])
@login_required
def delete_project_file(project_id, file_id):
    data = load_data()
    project = find_by_id(data["projetos"], project_id)
    if project:
        project["arquivos"] = [f for f in project.get("arquivos", []) if int(f.get("id", 0) or 0) != file_id]
        save_data(data)
    return redirect(url_for("project_detail", project_id=project_id))


if __name__ == "__main__":
    ensure_data_file()
    debug_flag = (os.environ.get("CRM_DEBUG") or "false").strip().lower() in ("1", "true", "yes", "on")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=debug_flag)
