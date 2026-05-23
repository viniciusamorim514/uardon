# Uardon - Operacao de Deploy

## Producao oficial

- Landing: Cloudflare Pages `uardon-landing`
- Pasta publicada: `web/`
- Dominios: `uardon.com.br` e `www.uardon.com.br`
- CRM/API: Railway em `https://app.uardon.com.br`
- Health do CRM: `https://app.uardon.com.br/health`

## Automacao escolhida

O caminho robusto e GitHub Actions publicando no Cloudflare Pages.

Motivo: o Cloudflare Pages nativo esta com falha ao buscar o repositorio. O GitHub Actions evita essa etapa quebrada: quando houver push no `main` alterando `web/`, o proprio GitHub envia a pasta para o projeto Pages oficial.

## Segredo necessario no GitHub

Criar no GitHub o segredo:

```text
CLOUDFLARE_API_TOKEN
```

O token precisa permitir deploy em Cloudflare Pages no projeto `uardon-landing`.

## Validacao rapida

1. Alterar um texto simples em `web/index.html`.
2. Fazer commit e push no `main`.
3. Abrir GitHub > Actions > `Deploy landing to Cloudflare Pages`.
4. Confirmar status verde.
5. Abrir `https://uardon.com.br` e confirmar o texto novo.
6. Abrir `https://app.uardon.com.br/health` e confirmar `ok: true`.

## Publicar landing no dia a dia

1. Editar arquivos dentro de `web/`.
2. Fazer commit.
3. Enviar para o GitHub.
4. Conferir a Action.
5. Conferir o site no ar.

## Publicar CRM no dia a dia

1. Editar arquivos do CRM em `crm_vitoria_source/`.
2. Fazer commit.
3. Enviar para o GitHub.
4. Conferir deploy no Railway.
5. Conferir `https://app.uardon.com.br/health`.

## Checklist diario da equipe (5 minutos)

1. Abrir `https://uardon.com.br` e validar carregamento da landing.
2. Abrir `https://app.uardon.com.br/health` e validar `ok: true`.
3. Abrir CRM e checar novos leads e tarefas do dia.
4. Validar ao menos 1 envio de lead de teste por semana.
5. Confirmar que nao ha deploy com falha no GitHub Actions e no Railway.

## Checklist de publicacao segura

1. Confirmar que a mudanca esta no repositorio correto (`uardon`).
2. Se for landing, alterar apenas `web/`.
3. Se for CRM, alterar apenas `crm_vitoria_source/`.
4. Fazer commit com mensagem clara.
5. Fazer push no `main`.
6. Validar status verde do deploy (GitHub Actions para landing, Railway para CRM).
7. Validar em producao:
   - landing publica
   - `/health` do CRM
   - fluxo de lead chegando no CRM

## Plano de emergencia (quando algo cair)

1. Confirmar impacto:
   - landing fora do ar
   - CRM fora do ar
   - formulario sem enviar
2. Verificar ultimo deploy:
   - GitHub Actions (landing)
   - Railway Deployments (CRM)
3. Se falhou por mudanca recente:
   - reverter ultimo commit no GitHub
   - aguardar novo deploy automatico
4. Se CRM estiver instavel:
   - validar variaveis do Railway
   - validar conexao com Postgres
   - validar `https://app.uardon.com.br/health`
5. Se formulario falhar:
   - validar endpoint `/v1/leads`
   - validar Turnstile
   - validar CORS de `uardon.com.br` e `www.uardon.com.br`
6. Registrar incidente com horario, causa e acao aplicada.

## Politica minima de seguranca operacional

1. Nunca compartilhar token em chat/print.
2. Rotacionar token apos exposicao acidental.
3. Usar apenas segredos no GitHub/Railway (nunca no codigo).
4. Evitar alteracao direta em producao sem commit no Git.
5. Manter backup de dados e uploads.

## Teste de lead em 2 minutos

1. Abrir `https://uardon.com.br`.
2. Preencher o formulario com um lead de teste claro, por exemplo `Teste Uardon`.
3. Concluir o Turnstile.
4. Enviar o formulario.
5. Abrir o CRM em `https://app.uardon.com.br`.
6. Confirmar que o lead entrou com origem/site preenchido.
