$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if (!(Test-Path ".venv")) {
    Write-Host "Ambiente nao encontrado. Rodando setup..."
    powershell -ExecutionPolicy Bypass -File ".\setup.ps1"
}

$server = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*saas.app.server*" -and $_.Name -like "python*"
} | Select-Object -First 1

if (!$server) {
    Write-Host "Iniciando Poder em Jogo Mobile Studio..."
    Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "-m", "saas.app.server" -WorkingDirectory $root -WindowStyle Hidden
    Start-Sleep -Seconds 5
}

try {
    Invoke-RestMethod "http://127.0.0.1:8790/health" -TimeoutSec 8 | Out-Null
} catch {
    Write-Host "Nao consegui confirmar o servidor local. Abra primeiro o app normal e tente de novo."
    exit 1
}

$cloudflared = Get-Command cloudflared -ErrorAction SilentlyContinue
if (!$cloudflared) {
    $knownCloudflared = @(
        "$env:ProgramFiles\cloudflared\cloudflared.exe",
        "${env:ProgramFiles(x86)}\cloudflared\cloudflared.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($knownCloudflared) {
        $cloudflared = [pscustomobject]@{ Source = $knownCloudflared }
    }
}

if (!$cloudflared) {
    Write-Host "cloudflared nao encontrado."
    Write-Host "Tentando instalar pelo winget..."
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (!$winget) {
        Write-Host "Winget nao esta disponivel. Instale Cloudflare Tunnel manualmente: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
        exit 1
    }
    winget install --id Cloudflare.cloudflared -e --accept-source-agreements --accept-package-agreements
    $cloudflared = Get-Command cloudflared -ErrorAction SilentlyContinue
    if (!$cloudflared) {
        $knownCloudflared = @(
            "$env:ProgramFiles\cloudflared\cloudflared.exe",
            "${env:ProgramFiles(x86)}\cloudflared\cloudflared.exe"
        ) | Where-Object { Test-Path $_ } | Select-Object -First 1
        if ($knownCloudflared) {
            $cloudflared = [pscustomobject]@{ Source = $knownCloudflared }
        }
    }
    if (!$cloudflared) {
        Write-Host "Instalacao concluida, mas o comando ainda nao apareceu neste terminal."
        Write-Host "Feche este PowerShell, abra de novo e rode este arquivo novamente."
        exit 1
    }
}

Write-Host ""
Write-Host "App local: http://127.0.0.1:8790"
Write-Host "Gerando link publico temporario..."
Write-Host "Copie a URL que terminar com .trycloudflare.com e abra no iPhone."
Write-Host "Mantenha esta janela aberta enquanto usar pelo celular."
Write-Host ""

& $cloudflared.Source tunnel --url "http://127.0.0.1:8790"
