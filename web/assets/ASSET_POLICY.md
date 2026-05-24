# Asset Policy (Landing Uardon)

Objetivo: evitar perda/troca acidental de logo e imagens oficiais.

## Regras

1. Arquivos oficiais da landing sao protegidos por hash em:
   - `web/assets/official-assets-lock.json`
2. Qualquer alteracao nesses arquivos deve passar por:
   - revisao visual
   - atualizacao do lock file
3. Nao substituir conteudo mantendo o mesmo nome em mudancas normais.
   - preferir nome versionado para evitar cache antigo.

## Fluxo seguro

1. Ajustar imagens/logo.
2. Revisar visual em preview.
3. Atualizar lock file com novos hashes.
4. Commit com mensagem clara.
5. Deploy.

## Arquivos oficiais atuais

- `asset-001-7cd039fdf24b.svg`
- `asset-002-bea613bdb145.png`
- `asset-003-9d8ec7ed1e84.svg`
- `hero-vitoria-sala-jantar.jpeg`
- `asset-004-vitoria.jpg` ate `asset-010-vitoria.jpg`
