import os
from pathlib import Path

INSTALLED_DIR = Path(r"V:\ARQUIVOS\OneDrive\Área de Trabalho\CRM Vitoria Uardon")

os.environ["CRM_DATA_FILE"] = str(INSTALLED_DIR / "data.json")
os.environ["CRM_UPLOAD_DIR"] = str(INSTALLED_DIR / "uploads")

import app as crm_app


crm_app.APP_DIR = INSTALLED_DIR


if __name__ == "__main__":
    crm_app.ensure_data_file()
    crm_app.app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)
