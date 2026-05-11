# Script simples para abrir o Dashboard
# Clique duplo neste arquivo para abrir o dashboard

# Ativar venv
Write-Host "Ativando ambiente Python..." -ForegroundColor Yellow
& .\.venv\Scripts\Activate.ps1

# Abrir dashboard no navegador
Write-Host "Abrindo Dashboard..." -ForegroundColor Green
Start-Process "http://localhost:8787/dashboard.html"

Write-Host ""
Write-Host "✓ Dashboard aberto!" -ForegroundColor Green
Write-Host "Se não abrir, copie e cole no navegador:" -ForegroundColor Yellow
Write-Host "http://localhost:8787/dashboard.html" -ForegroundColor Cyan
Write-Host ""
Write-Host "Nota: A aplicação (abrir_app.ps1) precisa estar rodando!" -ForegroundColor Yellow
