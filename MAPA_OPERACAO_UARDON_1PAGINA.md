# Mapa de Operação (1 Página) - Uardon

## 1) Onde fica o código
- Repositório principal: `https://github.com/viniciusamorim514/uardon`
- Branch de produção: `main`
- Pasta do CRM: `crm_vitoria_source/`
- Pasta da landing: `web/` (quando aplicável no fluxo atual)

## 2) Onde publica (deploy)
- CRM/API (`app.uardon.com.br`): Railway
  - Projeto: `exciting-solace`
  - Serviço: `web`
  - Fluxo: `push` no GitHub (`main`) -> deploy automático no Railway
- Landing (`uardon.com.br`): Cloudflare Pages/Workers
  - Fluxo: GitHub Actions -> Cloudflare

## 3) Onde configura domínio e DNS
- DNS e zona do domínio: Cloudflare
  - Domínio: `uardon.com.br`
  - Subdomínio CRM: `app.uardon.com.br`
- Ponto de atenção:
  - Alterações de DNS podem levar alguns minutos para propagar.

## 4) Onde ver logs
- CRM (app): Railway
  - Aba `Deploy Logs` (subida da aplicação)
  - Aba `HTTP Logs` (requisições e status)
- Auditoria de autenticação (dentro do CRM):
  - URL: `/admin/auditoria-auth`
  - Ver: login, reset, ações admin, falhas e bloqueios

## 5) Onde ver e-mail
- Envio transacional (reset/sistema): Resend
  - Monitor de envio e status: painel do Resend
- Caixa operacional da equipe: Umbler Webmail
  - E-mail operacional: `suporte@uardon.com.br`
- Política atual:
  - Remetente técnico: `noreply@uardon.com.br`
  - Caixa de operação: `suporte@uardon.com.br`

## 6) Quem é responsável por cada área
- Produto e operação comercial: Vitória Uardon
- CRM (regras, usuários, fluxo): Responsável CRM (definir nome)
- Infra e deploy (Railway/Cloudflare): Responsável técnico (definir nome)
- DNS e domínio: Responsável técnico (definir nome)
- E-mail operacional e atendimento: Responsável suporte (definir nome)

## 7) Rotina diária mínima (5 minutos)
1. Verificar saúde do CRM: `https://app.uardon.com.br/health`
2. Verificar Railway (último deploy e HTTP logs)
3. Verificar `/admin/auditoria-auth` no CRM
4. Verificar caixa `suporte@uardon.com.br` (entrada + spam)
5. Confirmar entrada de novos leads no CRM

## 8) Escalonamento rápido (quando algo falhar)
- Falha de login/reset:
  - Ver `/admin/auditoria-auth` + logs do Railway + Resend
- Falha de deploy:
  - Ver `Deploy Logs` no Railway e último commit publicado
- Falha de domínio/DNS:
  - Ver registros no Cloudflare (zona `uardon.com.br`)
- Falha de e-mail:
  - Ver status no Resend e caixa operacional na Umbler

## 9) Mensagem padrão para explicar hospedagem (comercial)
"A Uardon opera com arquitetura separada para estabilidade: landing em Cloudflare e CRM/API em Railway com banco Postgres, deploy automatizado por GitHub, trilha de auditoria e monitoramento de autenticação."

