from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
SAAS_DATA = ROOT / "outputs" / "saas"
OUTPUTS = ROOT / "outputs"
DB_PATH = SAAS_DATA / "studio.db"
LEADS_BACKUP_PATH = SAAS_DATA / "leads-backup.jsonl"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
MOBILE_WEB = ROOT / "saas" / "mobile"

DEFAULT_USER_ID = os.getenv("SAAS_DEFAULT_USER_ID", "local-owner")
MAX_PARALLEL_JOBS = int(os.getenv("SAAS_MAX_PARALLEL_JOBS", "1"))


def ensure_dirs() -> None:
    SAAS_DATA.mkdir(parents=True, exist_ok=True)
