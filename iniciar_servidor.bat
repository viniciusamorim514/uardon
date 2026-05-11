@echo off
echo Parando servidor antigo na porta 8787...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8787 " ^| findstr "LISTENING"') do (
    echo Matando processo %%a
    taskkill /f /pid %%a 2>nul
)
timeout /t 2 /nobreak >nul
echo Iniciando servidor novo...
cd /d "%~dp0"
.venv\Scripts\python.exe src\web_app.py
pause
