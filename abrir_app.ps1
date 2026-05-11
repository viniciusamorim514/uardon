# Script para iniciar a aplicação web - Poder em Jogo Studio v2.0
# Clique duplo para executar

cls
Write-Host "╔════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║  INICIANDO PODER EM JOGO STUDIO           ║" -ForegroundColor Cyan
Write-Host "║  (Web Studio - Renderização de Clipes)    ║" -ForegroundColor Cyan
Write-Host "╚════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

$ErrorActionPreference = "Continue"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

# 1. Verificar venv
if (!(Test-Path ".venv")) {
    Write-Host "⚠️  Ambiente Python não encontrado." -ForegroundColor Yellow
    Write-Host "   Rodando setup..." -ForegroundColor Yellow
    Write-Host ""
    powershell -ExecutionPolicy Bypass -File .\setup.ps1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Erro no setup!" -ForegroundColor Red
        Read-Host "Pressione ENTER para sair"
        exit 1
    }
}

# 2. Ativar venv
Write-Host "1️⃣  Ativando ambiente Python..." -ForegroundColor Yellow
& .\.venv\Scripts\Activate.ps1
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Erro ao ativar venv!" -ForegroundColor Red
    Read-Host "Pressione ENTER para sair"
    exit 1
}
Write-Host "   ✓ Ambiente ativado" -ForegroundColor Green
Write-Host ""

# 3. Verificar dependências
Write-Host "2️⃣  Verificando dependências..." -ForegroundColor Yellow
python -m pip install imageio-ffmpeg flask -q 2>$null
Write-Host "   ✓ Dependências ok" -ForegroundColor Green
Write-Host ""

# 4. Iniciar servidor
Write-Host "3️⃣  Iniciando servidor web..." -ForegroundColor Yellow
Write-Host "   Servidor rodará em: http://localhost:8787" -ForegroundColor Cyan
Write-Host ""
Write-Host "⏳ Aguarde 5 segundos... o navegador vai abrir automaticamente" -ForegroundColor Yellow
Write-Host ""

# Rodar servidor em background e abrir navegador
$job = Start-Job -ScriptBlock {
    Set-Location "C:\Users\Vinicius\Documents\New project\xadrez_geopolitico_automation"
    & .\.venv\Scripts\python.exe .\src\web_app.py
}

# Aguardar servidor ficar pronto
Start-Sleep -Seconds 3

# Tentar abrir no navegador
$url = "http://localhost:8787"
try {
    Start-Process $url
    Write-Host "✓ Navegador aberto!" -ForegroundColor Green
} catch {
    Write-Host "⚠️  Não consegui abrir o navegador automaticamente." -ForegroundColor Yellow
    Write-Host "   Copie e cole no navegador: $url" -ForegroundColor Cyan
}

Write-Host ""
Write-Host "╔════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║  ✅ SERVIDOR RODANDO!                     ║" -ForegroundColor Green
Write-Host "║  Se não abrir, copie e cole no navegador: ║" -ForegroundColor Green
Write-Host "║  http://localhost:8787                     ║" -ForegroundColor Green
Write-Host "║                                            ║" -ForegroundColor Green
Write-Host "║  Para ver o dashboard com métricas:       ║" -ForegroundColor Green
Write-Host "║  http://localhost:8787/dashboard.html     ║" -ForegroundColor Green
Write-Host "║                                            ║" -ForegroundColor Green
Write-Host "║  Feche esta janela para parar o servidor  ║" -ForegroundColor Green
Write-Host "╚════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""

# Manter servidor rodando
Wait-Job -Job $job
Receive-Job -Job $job
