# Poder em Jogo Automation

Automacao local para criar videos verticais do canal `@poderemjogo`.

O fluxo foi pensado para rodar no laptop, sem servidor:

1. Gera ideias e roteiros originais de geopolitica.
2. Cria narracao de IA em portugues.
3. Monta um video vertical em alta qualidade, com movimento, filtros e ritmo rapido.
4. Salva descricao, hashtags e checklist de publicacao.

O visual usa imagens realistas de apoio quando disponiveis via Wikimedia Commons, com creditos salvos em `creditos-imagens.txt` dentro da pasta do video. Se a busca falhar ou atingir limite temporario, o gerador usa um fundo editorial automatico.

Importante: este gerador cria videos explicativos originais. Para ficar com cara de "corte viral" de verdade, o formato ideal e usar um video-fonte autorizado, cortar o melhor trecho, aplicar crop vertical, punch-in, tracking de rosto e legenda sincronizada. O arquivo `CUTS_PLAYBOOK.md` registra o padrao que vamos seguir nessa evolucao.

O padrao recomendado agora e `alta`, em 1440x2560, porque fica mais nitido que 1080p e e bem mais leve que 4K no laptop. O modo 4K continua disponivel, mas pode demorar bastante.

## Instalacao

No PowerShell, dentro desta pasta:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

## Criar um video

```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1 -Topic "Por que a China compra tanto ouro?"
```

Voz padrao: `pt-BR-ThalitaMultilingualNeural`, com velocidade levemente reduzida para soar menos apressada. Para testar outra voz:

```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1 -Topic "Por que Taiwan importa tanto?" -Voice "pt-BR-FranciscaNeural" -VoiceRate "-4%"
```

Os arquivos finais ficam em:

```text
outputs/
```

## Criar varios videos

Edite `topics.txt` com um tema por linha e rode:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_batch.ps1
```

## Criar corte a partir de video longo

Quando voce tiver um podcast, live ou entrevista autorizada salva no laptop, use:

```powershell
.\.venv\Scripts\python.exe .\src\create_cut_from_source.py --source "C:\caminho\video.mp4" --start "00:12:34" --duration 75 --headline "NINGUEM ESTA OLHANDO PARA ESSE DETALHE"
```

Isso gera um corte vertical em alta qualidade com crop para TikTok, punch-in leve, gancho nos primeiros 5 segundos e audio normalizado.

Para escolher o texto do gancho inicial:

```powershell
.\.venv\Scripts\python.exe .\src\create_cut_from_source.py --source "C:\caminho\video.mp4" --start "00:12:34" --duration 75 --headline "NINGUEM ESTA OLHANDO PARA ESSE DETALHE" --hook "ESSE DETALHE MUDA TUDO"
```

## Criar corte a partir do YouTube

Use apenas videos seus, licenciados ou com permissao para corte. Para baixar e cortar em um comando:

```powershell
.\.venv\Scripts\python.exe .\src\youtube_to_cut.py --url "https://www.youtube.com/watch?v=..." --start "00:12:34" --duration 75 --headline "O MAPA QUE EXPLICA ESSA CRISE"
```

O arquivo final sai em `outputs/`, junto com um texto base de publicacao.

## Qualidade e gancho

Por padrao, os cortes novos usam:

- `--quality alta`: render em 1440x2560 com compressao menor para reduzir pixelacao;
- hook visual nos primeiros 5 segundos;
- audio da voz normalizado;
- sem musica de fundo por padrao;
- download em ate 720p por padrao. Em podcast longo, 1080p pode passar de 2 GB e travar o fluxo no laptop.

Se quiser forcar 4K:

```powershell
.\.venv\Scripts\python.exe .\src\make_top_cuts.py --count 3 --min-score 70 --quality 4k
```

Se um dia quiser testar musica de fundo manualmente, use um MP3 autorizado com `--music`:

```powershell
.\.venv\Scripts\python.exe .\src\make_top_cuts.py --count 3 --music "C:\caminho\musica.mp3" --music-volume 0.05
```

Se o rosto ficar muito para um lado, escolha o foco do corte:

```powershell
.\.venv\Scripts\python.exe .\src\make_top_cuts.py --count 3 --min-score 70 --focus left
```

Opcoes: `--focus left`, `--focus center` ou `--focus right`.

Se o video ficar pixelado, quase sempre o problema e o arquivo-fonte. O robo agora usa Deno + `yt-dlp-ejs` para tentar liberar 720p no YouTube. Se o YouTube so entregar 360p, o render melhora compressao e nitidez, mas nao consegue criar detalhe real que nao existe no video original.

## Versao local estilo OpusClip

Use este comando para fazer o fluxo automatico atual:

```powershell
.\.venv\Scripts\python.exe .\src\auto_pipeline.py --url "https://www.youtube.com/watch?v=..." --count 3 --min-score 75
```

Ele primeiro analisa a transcricao, escolhe os melhores candidatos, baixa apenas cada trecho escolhido, renderiza, valida qualidade e registra tudo no historico local do Studio.
Se um candidato for reprovado pelo controle de qualidade, o fluxo automatico tenta o proximo candidato em vez de entregar um corte ruim.

O fluxo antigo completo tambem continua disponivel:

```powershell
.\.venv\Scripts\python.exe .\src\opus_local.py --url "https://www.youtube.com/watch?v=..." --count 3 --min-score 70
```

Ou use o comando mais simples:

```powershell
powershell -ExecutionPolicy Bypass -File .\cortar_podcast.ps1
```

Por padrao, o app e o `cortar_podcast.ps1` usam fonte temporaria: o podcast bruto pode ser baixado durante o processamento, mas e removido no final. Ficam salvos apenas os cortes finais, relatorios e textos de publicacao.

Se usar o comando Python direto e tambem quiser remover o podcast bruto no final, adicione:

```powershell
--discard-source
```

## Usar como app

Agora existe um Studio local em navegador para usar o robo sem lembrar comandos.

Abra este arquivo na pasta do projeto:

```text
Abrir Poder em Jogo.bat
```

Ou rode no PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\abrir_app.ps1
```

No app voce consegue:

- colar link do YouTube;
- monitorar canais de podcasts completos na aba Radar;
- separar videos curtos em uma aba Shorts propria;
- detectar episodios novos pelo feed publico do YouTube;
- mandar episodio novo direto para a fila de cortes;
- ativar corte automatico quando sair episodio novo enquanto o Studio estiver aberto;
- criar uma linha de base ao adicionar fonte, evitando cortar episodios antigos automaticamente;
- montar fila com varios links;
- definir quantidade de cortes, score minimo e duracao;
- escolher IA editorial, qualidade e foco do rosto;
- analisar candidatos antes de renderizar;
- ver candidatos com score, duracao, motivo e thumbnail;
- aprovar, descartar ou renderizar candidato escolhido;
- ver cortes prontos em lista;
- ver historico local dos jobs processados;
- carregar e copiar legenda/descricao/hashtags dentro do app;
- abrir `outputs`, `_postar_agora`, relatorio e pre-aprovacao com um clique;
- acompanhar progresso em barra de 0 a 100%.
- ver percentual grande, etapa atual e trilha visual de progresso.

O app abre no navegador em:

```text
http://127.0.0.1:8787
```

Ele continua rodando localmente no seu laptop. Nao e um servidor publico.
O Radar funciona enquanto o Studio estiver aberto. Ele verifica as fontes a cada 15 minutos e guarda estado em `outputs\radar_state.json`; as fontes ficam em `config\radar_sources.json`.
Ao clicar em `Buscar novidades`, se houver episodio novo em fonte automatica, ele entra na fila na hora.
Fontes marcadas como `Podcast completo` aparecem no Radar principal. Fontes marcadas como `Shorts` aparecem na aba Shorts e usam configuracao curta. O robo tambem tenta separar automaticamente pelo link `/shorts/` e pela duracao do video.
O Radar principal faz varredura profunda na aba `/streams` dos canais, lista ate 50 podcasts completos por fonte e prioriza os publicados nos ultimos 15 dias. Isso evita depender apenas do feed curto do YouTube, que costuma trazer poucos itens misturados com Shorts.
Cada episodio recebe um `episode_score` de 0 a 100 antes do corte. O score considera recencia, duracao, formato de podcast, tema quente para o canal, potencial de conflito/comentario e possiveis penalizacoes como conteudo restrito ou pouco aderente.
O Radar tambem consulta noticias recentes via Google News RSS e grava cache em `outputs\trend_cache.json`. Quando um termo do episodio aparece em alta nas noticias, o episodio recebe `trend_score` e ganha bonus no ranking.
O Radar mostra a decomposicao do score, como `Recencia`, `Duracao`, `Trend noticias`, `Tema quente` e `Formato`, e tambem exibe uma decisao editorial: `Prioridade alta`, `Testar hoje`, `Baixa prioridade` ou `Ignorar por enquanto`.
O botao `Analisar agora` no Radar baixa apenas a transcricao e gera candidatos, sem renderizar video. A aba `Postar hoje` organiza os cortes prontos em prioridade de publicacao.

Ele faz:

- analisa candidatos primeiro e so baixa os trechos escolhidos;
- tenta baixar video + audio em ate 1080p e juntar com FFmpeg;
- rejeita fonte ruim abaixo de 720p;
- baixa transcricao;
- encontra trechos virais;
- prioriza cortes de 45 a 60 segundos por padrao, porque os prints atuais mostram baixa conclusao;
- calcula score;
- calcula `gancho inicial` para priorizar cortes que prendem nos primeiros segundos;
- penaliza trechos que comecam soltos, com pronome sem contexto ou apresentacao de convidado;
- limpa repeticoes da legenda automatica do YouTube antes de criar titulo e descricao;
- ajusta automaticamente a entrada do corte alguns segundos para frente ou para tras se isso melhorar o gancho;
- avalia contexto editorial: gancho, clareza, conflito, progressao, valor e potencial de comentario;
- detecta foco do rosto;
- mantem pausas por padrao para preservar a sincronia entre audio e boca;
- deixa o video limpo por padrao, para usar a legenda nativa do TikTok;
- gera uma versao limpa por corte por padrao, para evitar pastas duplicadas;
- gera cortes prontos em `outputs/`;
- separa o melhor corte em `outputs\_postar_agora\`, com nome simples para upload;
- cria `publicacao.txt` com legenda baseada no conteudo real do corte, 5 hashtags e horario sugerido;
- cria `outputs\pre-aprovacao\` com frame inicial, score, motivo e descricao antes de renderizar;
- cria indice em `outputs\opus-local\ultimos-cortes.md`.

Depois que terminar, primeiro olhe esta pasta:

```text
outputs\_postar_agora\
```

Ela guarda o video recomendado para postar, o `publicacao.txt` e um `LEIA-ME.txt`.

Se quiser queimar legenda no video, adicione `--burn-subtitles`.

O comando normal gera apenas uma versao:

```powershell
powershell -ExecutionPolicy Bypass -File .\cortar_podcast.ps1 -SemIAEditorial
```

Para analisar os melhores trechos sem renderizar video:

```powershell
powershell -ExecutionPolicy Bypass -File .\cortar_podcast.ps1 -AnaliseApenas -Quantidade 5
```

Para gerar um relatorio visual antes de renderizar:

```powershell
powershell -ExecutionPolicy Bypass -File .\cortar_podcast.ps1 -PreviaApenas -Quantidade 5
```

O relatorio fica em:

```text
outputs\pre-aprovacao\
```

Depois de escolher um numero no relatorio, renderize apenas aquele candidato:

```powershell
powershell -ExecutionPolicy Bypass -File .\cortar_podcast.ps1 -RenderizarCandidato 1
```

Isso usa o ultimo `candidatos.json`, gera o video final e cria o pacote em:

```text
outputs\_postar_agora\
```

Se quiser testar duas variacoes manualmente:

```powershell
powershell -ExecutionPolicy Bypass -File .\cortar_podcast.ps1 -SemIAEditorial -DuasVersoes
```

### IA editorial

Sem chave da OpenAI, o robo usa uma avaliacao editorial local mais simples.
Com chave, ele envia os melhores trechos da transcricao para a OpenAI avaliar contexto e criar titulos melhores.

Para ativar IA real, crie um arquivo `.env` na pasta do projeto assim:

```text
OPENAI_API_KEY=sua_chave_aqui
OPENAI_MODEL=gpt-4.1-mini
```

Depois rode normalmente:

```powershell
powershell -ExecutionPolicy Bypass -File .\cortar_podcast.ps1
```

Para exigir IA e dar erro se a chave nao estiver configurada:

```powershell
powershell -ExecutionPolicy Bypass -File .\cortar_podcast.ps1 -ExigirIAEditorial
```

Para desligar totalmente a IA editorial:

```powershell
powershell -ExecutionPolicy Bypass -File .\cortar_podcast.ps1 -SemIAEditorial
```

Para cortar pausas manualmente em teste:

```powershell
.\.venv\Scripts\python.exe .\src\opus_local.py --url "https://www.youtube.com/watch?v=..." --cut-pauses
```

Para testar com arquivo ja baixado ou quando o YouTube limitar a qualidade:

```powershell
.\.venv\Scripts\python.exe .\src\opus_local.py --url "https://www.youtube.com/watch?v=..." --source ".work\youtube\video.mp4" --allow-low-quality --count 1
```

## Encontrar possiveis trechos virais

Antes de cortar, o robo pode analisar a legenda do video e sugerir os melhores trechos:

```powershell
.\.venv\Scripts\python.exe .\src\find_viral_moments.py --url "https://www.youtube.com/watch?v=..." --top 5
```

Ele cria:

```text
outputs/viral-moments/candidatos-virais.md
outputs/viral-moments/candidatos-virais.json
```

O relatorio ja vem com o comando pronto para cortar cada candidato.

Por padrao, a avaliacao agora combina:

- texto da legenda/transcricao;
- forca dos primeiros segundos do trecho;
- energia e picos da voz;
- pausas e trechos silenciosos;
- variacao de volume;
- mudancas visuais/cenas detectadas no video.

Se quiser uma analise mais rapida usando apenas texto:

```powershell
.\.venv\Scripts\python.exe .\src\find_viral_moments.py --url "https://www.youtube.com/watch?v=..." --top 5 --no-media-analysis
```

## Gerar varios cortes ranqueados

Depois que o relatorio existir, gere os melhores cortes automaticamente:

```powershell
.\.venv\Scripts\python.exe .\src\make_top_cuts.py --count 3 --min-score 60 --no-headline
```

O robo vai:

- usar os melhores candidatos do relatorio;
- respeitar score minimo de 0 a 100;
- gerar varios videos em `outputs/`;
- criar um arquivo `score-viral.txt` dentro da pasta de cada corte.

Use `--count 5` se quiser cinco cortes. Use `--min-score 70` para gerar apenas trechos fortes.

## Acompanhar desempenho

Use `analytics.csv` para registrar os resultados depois de publicar cada video.
O arquivo `STRATEGY.md` tem formatos, ganchos e rotina semanal para transformar os dados em proximas pautas.

Para analisar os ultimos videos do TikTok Studio, preencha `analytics.csv` com as metricas principais:

- views em 1h, 24h e 7d;
- retencao media;
- tempo medio assistido;
- percentual que assistiu completo;
- curtidas, comentarios, compartilhamentos, salvamentos e seguidores ganhos;
- gancho, hashtags e horario de publicacao.

Depois rode:

```powershell
.\.venv\Scripts\python.exe .\src\analyze_tiktok_metrics.py
```

Ele cria:

```text
outputs\tiktok-analytics\aprendizado.md
outputs\tiktok-analytics\aprendizado.json
```

Use esse relatorio para escolher os proximos temas e hooks.

O Studio tambem usa esse aprendizado automaticamente no score dos novos candidatos.
Se `analytics.csv` mudar, `outputs\tiktok-analytics\aprendizado.json` e atualizado na proxima analise.

## Controle de qualidade automatico

Todo corte renderizado passa por uma validacao tecnica e gera:

```text
qualidade.txt
qualidade.json
```

A checagem olha resolucao, formato 9:16, audio, decodificacao, duracao final, bitrate, bordas pretas e rosto centralizado.
O status pode ser `aprovado`, `revisar` ou `reprovado`. Cortes reprovados nao entram como pacote recomendado para postar.

## Opcional: melhorar roteiro com OpenAI

Se voce tiver uma chave da OpenAI, defina:

```powershell
$env:OPENAI_API_KEY="sua-chave"
$env:OPENAI_MODEL="gpt-4.1-mini"
```

Sem chave, o projeto usa um gerador local com modelos de roteiro. Ele e mais simples, mas ja permite produzir videos originais.

## Estrategia recomendada

- Publique videos de 60 a 90 segundos.
- Use conteudo original, narrado e editado, ou cortes de videos que voce tenha permissao para usar.
- Use texto curto na tela; a narracao explica, a tela prende a atencao.
- Troque o visual a cada 1 a 3 segundos para criar interrupcao de padrao.
- Prefira render final 4K para manter nitidez depois da compressao do TikTok.
- Crie series: "Xadrez em 60s", "Mapa do Poder", "O que ninguem te explicou".
- Meça retencao, comentarios, salvamentos e seguidores por video.
- Reaproveite os temas vencedores em novas variacoes.

## Padrao aprendido na pesquisa

- Hook antes de 2 segundos.
- Movimento e som importam mais do que slide bonito.
- Legenda grande e sincronizada segura retencao.
- Cortes fortes usam rosto, punch-in, pausas removidas e pergunta final.
- Para monetizacao, priorize originalidade e videos acima de 1 minuto quando fizer sentido.

## Observacao sobre publicacao

Este MVP gera os videos e materiais para postagem. A publicacao automatica no TikTok depende de permissoes/API da conta e deve respeitar as regras da plataforma.
