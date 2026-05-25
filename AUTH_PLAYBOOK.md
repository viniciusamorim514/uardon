# Uardon CRM - Playbook de Autenticacao

## 1) Incidente de autenticacao (resumo)
Quando houver pico de falhas de login/reset ou falha de entrega de reset:

1. Acessar `/admin/auditoria-auth`.
2. Filtrar por:
   - evento: `password_reset_sent`
   - status: `failed`
3. Confirmar:
   - quantidade no resumo diario;
   - codigo do erro (`provider_error`, etc.);
   - destinatario final (`details.delivered_to`).
4. Acao imediata:
   - se repetitivo, manter `support_only`;
   - revisar variaveis de e-mail no Railway;
   - validar dominio/registro no Resend.

## 2) Recuperacao de senha (operacao segura)
Fluxo padrao:
1. Usuario clica em `Esqueci minha senha`.
2. Sistema envia link com TTL e invalida tokens antigos.
3. Usuario redefine senha conforme politica forte.

Validacoes operacionais:
1. Testar 2 solicitacoes seguidas (cooldown).
2. Confirmar envio no painel de auditoria.
3. Confirmar recebimento em caixa operacional (`support_only`) ou caixa do usuario (`target`).

## 3) Troca de senha e politica
Regras ativas:
- minimo de 10 caracteres
- 1 maiuscula
- 1 minuscula
- 1 numero
- 1 simbolo
- expiracao por idade de senha (rotacao)

Recomendacao:
- nao reutilizar senha simples;
- revisar expiracoes semanalmente para usuarios internos.

## 4) Acao admin sensivel (duas etapas)
Acoes protegidas:
- ativar/inativar usuario
- troca de perfil
- envio de reset admin

Passos:
1. Admin inicia acao.
2. CRM envia codigo de aprovacao para e-mail do admin.
3. Admin informa codigo e confirma.
4. Evento fica registrado em auditoria.

## 5) Rotina diaria minima
1. Verificar `/health`.
2. Verificar resumo diario em `/admin/auditoria-auth`.
3. Confirmar ausencia de alerta critico de reset.
4. Executar 1 teste de reset controlado.

## 6) Regra de evolucao assistida -> producao
- Fase assistida: `PASSWORD_RESET_DELIVERY_MODE=support_only`
- Fase producao: `PASSWORD_RESET_DELIVERY_MODE=target`
- Mudar para `target` somente apos estabilidade (ver `AUTH_EMAIL_POLICY.md`).
