import json
import os
import shutil
from datetime import datetime
from pathlib import Path

try:
    import psycopg
except Exception:
    psycopg = None


def fix_mojibake_text(value):
    if not isinstance(value, str):
        return value
    if "Ã" not in value and "Â" not in value and "�" not in value:
        return value
    try:
        fixed = value.encode("latin-1").decode("utf-8")
        return fixed if fixed else value
    except Exception:
        return value


def normalize_payload(value):
    if isinstance(value, dict):
        return {k: normalize_payload(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize_payload(v) for v in value]
    return fix_mojibake_text(value)


def sanitize_file(data_file):
    if not data_file.exists():
        return False, f"Arquivo nao encontrado: {data_file}"
    raw = data_file.read_text(encoding="utf-8-sig")
    data = json.loads(raw) if raw.strip() else {}
    normalized = normalize_payload(data)
    if normalized == data:
        return False, "Sem alteracoes no arquivo local."
    backup = data_file.with_suffix(f".backup_{datetime.now():%Y%m%d_%H%M%S}.json")
    shutil.copy2(data_file, backup)
    data_file.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return True, f"Arquivo saneado. Backup: {backup}"


def sanitize_db(database_url):
    if not database_url:
        return False, "DATABASE_URL nao configurada; pulando banco."
    if psycopg is None:
        return False, "psycopg nao instalado; pulando banco."
    conn = psycopg.connect(database_url)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT payload FROM crm_state WHERE id = 1")
            row = cur.fetchone()
            if not row or not row[0]:
                return False, "Sem payload no banco."
            payload = row[0]
            normalized = normalize_payload(payload)
            if normalized == payload:
                return False, "Sem alteracoes no payload do banco."
            cur.execute(
                """
                UPDATE crm_state
                SET payload = %s::jsonb, updated_at = NOW()
                WHERE id = 1
                """,
                (json.dumps(normalized, ensure_ascii=False),),
            )
        conn.commit()
        return True, "Payload do banco saneado."
    finally:
        conn.close()


def main():
    data_file = Path(os.environ.get("CRM_DATA_FILE", "crm_vitoria_source/data.json"))
    db_url = (os.environ.get("DATABASE_URL") or "").strip()
    file_changed, file_msg = sanitize_file(data_file)
    db_changed, db_msg = sanitize_db(db_url)
    print(file_msg)
    print(db_msg)
    if file_changed or db_changed:
        print("Saneamento concluido com alteracoes.")
    else:
        print("Saneamento concluido sem alteracoes.")


if __name__ == "__main__":
    main()
