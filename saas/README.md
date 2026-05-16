# Uardon CRM API

Base do backend usado pela landing e pelos fluxos internos da Uardon.

## Rodar API local

```powershell
cd "C:\Users\Vinicius\Documents\New project\Uardon"
powershell -ExecutionPolicy Bypass -File .\abrir_saas_dev.ps1
```

URL:

```text
http://127.0.0.1:8790
```

## Endpoints

### Health

```powershell
Invoke-RestMethod http://127.0.0.1:8790/health
```

### Criar corte

```powershell
$body = @{
  url = "https://www.youtube.com/watch?v=COLE_AQUI"
  count = 3
  min_score = 75
  min_duration = 45
  max_duration = 90
  quality = "alta"
  ai_mode = "auto"
  preview_only = $false
} | ConvertTo-Json

Invoke-RestMethod http://127.0.0.1:8790/v1/cortes -Method Post -ContentType "application/json" -Body $body
```

### Ver cortes

```powershell
Invoke-RestMethod http://127.0.0.1:8790/v1/cortes
```

### Ver um processamento

```powershell
Invoke-RestMethod http://127.0.0.1:8790/v1/cortes/ID_DO_PROCESSAMENTO
```

## Arquitetura atual

- `server.py`: API HTTP sem dependencias externas.
- `db.py`: SQLite local.
- `worker.py`: chama `src/opus_local.py`.
- `settings.py`: caminhos e configuracoes.

## Por que ainda nao e App Store

Esta camada e o inicio do backend. Para App Store faltam:

- autenticacao real;
- storage de video em nuvem;
- worker separado;
- frontend mobile nativo;
- pagamentos;
- politicas legais;
- deploy cloud.
