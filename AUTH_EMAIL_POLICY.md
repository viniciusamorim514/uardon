# Uardon CRM - Politica de E-mail Operacional

## Objetivo
Padronizar envios transacionais do CRM e separar claramente remetente tecnico de caixa operacional.

## Regra fixa
- Remetente tecnico transacional: `noreply@uardon.com.br`
- Caixa oficial de operacao: `suporte@uardon.com.br`
- Remetente tecnico nao deve ser usado como caixa de trabalho da equipe.

## Variaveis obrigatorias (Railway)
- `RESEND_FROM = Uardon CRM <noreply@uardon.com.br>`
- `OPERATIONS_INBOX_EMAIL = suporte@uardon.com.br`

## Modo de entrega de reset de senha
- `PASSWORD_RESET_DELIVERY_MODE = target`
  - Envia para o e-mail do proprio usuario (modo recomendado para producao).
- `PASSWORD_RESET_DELIVERY_MODE = support_only`
  - Envia sempre para a caixa operacional (`OPERATIONS_INBOX_EMAIL`).
  - Usar em homologacao/operacao assistida quando necessario.

## Observacoes
- O painel `/admin/auditoria-auth` registra o destinatario final em `details.delivered_to`.
- Para evitar dependencia de Outlook em operacao, priorize monitoramento da caixa `suporte@uardon.com.br`.
