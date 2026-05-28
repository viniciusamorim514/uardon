# Telegram de Alertas do Uardon CRM

## Objetivo
Receber alertas críticos de autenticação no Telegram automaticamente.

## Variáveis no Railway (serviço `web`)
- `TELEGRAM_BOT_TOKEN` = token do BotFather
- `TELEGRAM_CHAT_ID` = id do chat/grupo que receberá alertas

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

## Observação operacional
- Se as variáveis não estiverem definidas, o CRM continua funcionando normalmente (sem Telegram).
