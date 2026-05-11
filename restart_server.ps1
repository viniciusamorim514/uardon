# Kill any existing python processes on port 8787
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

# Start new server
Write-Host "Iniciando servidor..." -ForegroundColor Green
cd "C:\Users\Vinicius\Documents\New project\xadrez_geopolitico_automation"
& .\.venv\Scripts\python.exe .\src\web_app.py
