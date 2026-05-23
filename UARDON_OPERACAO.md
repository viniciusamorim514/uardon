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

## Teste de lead em 2 minutos

1. Abrir `https://uardon.com.br`.
2. Preencher o formulario com um lead de teste claro, por exemplo `Teste Uardon`.
3. Concluir o Turnstile.
4. Enviar o formulario.
5. Abrir o CRM em `https://app.uardon.com.br`.
6. Confirmar que o lead entrou com origem/site preenchido.
