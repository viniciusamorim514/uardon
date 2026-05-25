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

## Regra de transicao (fase assistida -> producao)
1. Manter `support_only` por no minimo 3 dias com estabilidade.
2. Critério de estabilidade:
   - nenhum `provider_error` nas ultimas 24h;
   - entrega confirmada de reset em testes diarios;
   - sem alerta critico de 2 falhas consecutivas.
3. Ao cumprir criterios, alterar para:
   - `PASSWORD_RESET_DELIVERY_MODE = target`
4. Validar 3 testes apos troca:
   - reset usuario real,
   - reset admin,
   - verificacao em `/admin/auditoria-auth`.

## Observacoes
- O painel `/admin/auditoria-auth` registra o destinatario final em `details.delivered_to`.
- Para evitar dependencia de Outlook em operacao, priorize monitoramento da caixa `suporte@uardon.com.br`.
