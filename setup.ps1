$ErrorActionPreference = "Stop"

if (!(Test-Path ".venv")) {
    python -m venv .venv
}

.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

Write-Host ""
Write-Host "Pronto. Agora rode:"
Write-Host '.\run.ps1 -Topic "Por que a China compra tanto ouro?"'
