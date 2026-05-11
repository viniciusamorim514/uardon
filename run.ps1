param(
    [Parameter(Mandatory=$true)]
    [string]$Topic,

    [string]$Voice = "pt-BR-ThalitaMultilingualNeural",
    [string]$VoiceRate = "-4%",
    [string]$VoicePitch = "+0Hz"
)

$ErrorActionPreference = "Stop"

if (!(Test-Path ".venv")) {
    Write-Host "Ambiente nao encontrado. Rodando setup..."
    powershell -ExecutionPolicy Bypass -File .\setup.ps1
}

.\.venv\Scripts\python.exe .\src\create_video.py --topic $Topic --voice $Voice --voice-rate $VoiceRate --voice-pitch $VoicePitch
