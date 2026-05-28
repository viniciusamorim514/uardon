# Telegram de Alertas do Uardon CRM

## Objetivo
Receber alertas críticos de autenticação no Telegram automaticamente.

## Variáveis no Railway (serviço `web`)
- `TELEGRAM_BOT_TOKEN` = token do BotFather
- `TELEGRAM_CHAT_ID` = id do chat/grupo que receberá alertas
- `TELEGRAM_WEBHOOK_SECRET` = segredo opcional para proteger comandos do bot
- `AGENT_CONTROL_SECRET` = segredo para o Codex ler o estado do agente via API

## Como obter rapidamente
1. No Telegram, fale com `@BotFather` e crie um bot (`/newbot`).
2. Copie o token gerado e coloque em `TELEGRAM_BOT_TOKEN`.
3. Envie qualquer mensagem para seu bot (ou adicione o bot no grupo).
4. Abra no navegador:
   - `https://api.telegram.org/bot<SEU_TOKEN>/getUpdates`
5. Localize `chat.id` no JSON e coloque em `TELEGRAM_CHAT_ID`.

## O que é enviado
- Alerta de autenticação com falha (`failed`, `provider_error`, `lock_active`)
- Alerta crítico de 2 falhas seguidas de envio de reset

## Comandos operacionais no Telegram
- `/help` ou `/start` = lista de comandos
- `/status` = saúde operacional geral (auth + leads + HTTP)
- `/auth_hoje` = resumo de login/reset no dia
- `/leads_hoje` = resumo rápido do funil comercial
- `/agente_status` = status do modo agente no CRM
- `/agente_on` = ativa modo agente no CRM
- `/agente_off` = pausa modo agente no CRM

## Ativar webhook (obrigatório para comandos)
Depois de configurar as variáveis:

1. Defina o endpoint:
   - sem segredo:
     - `https://app.uardon.com.br/telegram/webhook`
   - com segredo:
     - `https://app.uardon.com.br/telegram/webhook/<TELEGRAM_WEBHOOK_SECRET>`
2. Registre no Telegram:
   - `https://api.telegram.org/bot<SEU_TOKEN>/setWebhook?url=<URL_ENDPOINT>`
3. Verifique:
   - `https://api.telegram.org/bot<SEU_TOKEN>/getWebhookInfo`
4. Teste:
   - No chat do bot, envie `/status`.

## Endpoint para orquestração automática (Codex)
- URL: `https://app.uardon.com.br/ops/agent-state/<AGENT_CONTROL_SECRET>`
- Retorno:
  - `agent_enabled = true/false` (ligado pelo `/agente_on` e desligado pelo `/agente_off`)
  - `ops` com resumo operacional
- Uso:
  - O executor automático do Codex consulta esse endpoint e só roda melhorias quando `agent_enabled=true`.

## Observação operacional
- Se as variáveis não estiverem definidas, o CRM continua funcionando normalmente (sem Telegram).
- Comandos só são aceitos do `TELEGRAM_CHAT_ID` configurado.
