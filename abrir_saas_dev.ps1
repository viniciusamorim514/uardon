$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if (!(Test-Path ".venv")) {
    powershell -ExecutionPolicy Bypass -File ".\setup.ps1"
}

.\.venv\Scripts\python.exe -m pip install -r requirements-saas.txt
.\.venv\Scripts\python.exe -m saas.app.server
