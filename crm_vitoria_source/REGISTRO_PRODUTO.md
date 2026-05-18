# CRM Vitoria Uardon - Registro de Produto

Atualizado em: 30/04/2026

## Estado Atual

- CRM instalado e rodando no laptop da Vitoria.
- Dados reais preservados em `data.json`.
- Arquivos reais preservados em `uploads`.
- Atualizacao oficial aplicada via script com backup automatico.
- Base-fonte consolidada em `crm_vitoria_source`.
- Novo `.exe` gerado com PyInstaller.
- Formulario publico local `/orcamento` funcionando.
- Login por usuario e por e-mail funcionando:
  - usuario: `vitoria`
  - e-mail: `vit.cs99@gmail.com`
  - senha atual: `123456`

## Entregue Hoje

- Rota publica `/orcamento`.
- Pagina de orcamento com identidade visual da Vitoria.
- Envio do formulario gravando em Leads.
- Leads do formulario entram com:
  - origem: Instagram
  - etapa: Orcamento recebido
  - status: Novo
- Notificacao no sino para novos orcamentos vindos do Instagram.
- Dashboard preparado para destacar novos orcamentos.
- Correcao da rota `/clientes` na base-fonte.
- Validacao local com copia de dados.
- Validacao do `.exe` gerado.
- Publicacao do update na pasta oficial do Google Drive.
- Aplicacao no CRM instalado com backup.

## Regra de Ouro

Nunca substituir no laptop da Vitoria:

- `data.json`
- `uploads`

Ao atualizar, substituir somente:

- `CRM Vitoria Uardon.exe`
- `_internal`

## Rotas Validadas

- `/orcamento`
- `/`
- `/login`
- `/clientes`
- `/clientes/1`
- `/projetos`
- `/projetos/1`
- `/leads`
- `/tarefas`
- `/feedbacks`
- `/agenda`

## Proximos Passos Recomendados

### 1. Link publico temporario para teste

Objetivo: validar se a pagina de orcamento converte no Instagram.

Recomendacao:
- usar Cloudflare Tunnel ou ngrok apenas como teste controlado.
- nao expor o laptop da Vitoria como solucao definitiva.
- testar com poucas pessoas antes de postar amplamente.

Resultado esperado:
- link publico temporario apontando para `/orcamento`.
- primeiro ciclo real de leads entrando no CRM.

### 2. Melhorar conversao da pagina de orcamento

Objetivo: transformar a pagina em captacao real, nao apenas formulario.

Melhorias:
- titulo mais comercial.
- texto inicial mais direto.
- campos em ordem de decisao.
- confirmacao pos-envio mais elegante.
- CTA para WhatsApp apos envio.
- mensagem deixando claro o proximo passo.

### 3. Dashboard comercial

Objetivo: deixar os novos orcamentos impossiveis de ignorar.

Melhorias:
- bloco "Novos orcamentos".
- contador de leads Instagram.
- atalho para WhatsApp Web.
- filtro rapido em Leads: "Orcamento recebido".
- diferenciar lead novo, em contato e convertido.

### 4. Esteira de leads

Objetivo: transformar lead em cliente com fluxo simples.

Etapas recomendadas:
- Novo
- Contato feito
- Briefing marcado
- Proposta enviada
- Fechado
- Perdido

Evitar:
- funil complexo demais.
- automacao pesada antes de uso real.

### 5. Link publico definitivo

Objetivo: preparar comercializacao futura.

Caminho correto:
- formulario hospedado fora do laptop.
- dominio ou subdominio proprio.
- CRM local sincroniza os leads recebidos.
- dados protegidos, sem depender do laptop aberto na internet.

### 6. Instalacao mais profissional

Objetivo: app instalado de verdade no laptop.

Melhorias:
- atalho final na area de trabalho.
- icone correto.
- script de update com mensagens mais limpas.
- checagem automatica de versao.
- backup antes de cada atualizacao.

### 7. Produto comercial

Objetivo: sair de CRM interno para metodo vendavel.

Modulos fortes:
- Mesa do Dia.
- Clientes 360.
- Projetos Guiados.
- Follow-up e Sino.
- Cobranca Amigavel.
- Biblioteca de Modelos.
- Captacao pelo Instagram.

Principio:
- vender clareza operacional para arquitetas, nao um ERP.

## 01/05/2026 - Agenda como motor de proxima acao

Entregue:
- ao concluir compromisso vinculado a cliente/projeto, o CRM cria uma tarefa automatica quando ha sinal claro de proximo passo.
- regras iniciais: briefing/medicao, apresentacao 3D, layout, proposta/orcamento e reuniao.
- evento pessoal ou sem vinculo nao gera tarefa, para evitar poluicao operacional.
- cada compromisso gera no maximo uma tarefa automatica, mesmo se for concluido mais de uma vez.
- compromisso concluido continua registrando historico no cliente e no projeto.
- chip visual "Proxima acao" aparece no compromisso quando a tarefa foi criada.

Validado:
- teste isolado criou 1 tarefa, nao duplicou e ignorou evento pessoal.
- rotas principais passaram com dados reais.
- novo executavel gerado e aplicado no app instalado com backup.

Backup da aplicacao instalada:
- backup_20260501_133546

## 01/05/2026 - Mesa de tarefas por origem

Entregue:
- tela de tarefas reorganizada como mesa de comando.
- cards principais: abertas, atrasadas, hoje e proximas.
- bloco "Mesa do dia" com atrasadas, hoje e proximas acoes.
- bloco "Pendencias por origem": Leads, Agenda, Cobranca, Contratos, Projetos, Clientes e Manuais.
- cada tarefa continua clicavel e abre seu destino operacional.
- acao visivel mantida simples: Concluir.
- classificacao por origem no backend, sem alterar dados existentes.

Validado:
- sintaxe do backend.
- rota /tarefas com dados reais.
- rotas principais no executavel instalado.

Backup da aplicacao instalada:
- backup_20260501_134637

## 01/05/2026 - Dashboard como central de comando

Entregue:
- dashboard refeito para responder "o que precisa de acao hoje".
- topo consolidado com Recebiveis, Leads, Tarefas, Agenda, Contratos e Clientes.
- lista unica de prioridades do dia, sem blocos repetidos.
- Comercial separado com metricas e novos orcamentos.
- Agenda e tarefas no mesmo bloco operacional.
- Esteira de atendimento mantida como visao comercial.
- Projetos e relacionamento ficam em apoio, sem dominar a primeira tela.

Validado:
- rota / com dados reais.
- rotas relacionadas: /tarefas, /agenda, /leads, /recebiveis.
- executavel instalado validado nas rotas principais.

Backup da aplicacao instalada:
- backup_20260501_135130

## 01/05/2026 - Cliente 360 operacional

Entregue:
- Cliente 360 reorganizado para leitura comercial e operacional.
- bloco de proxima melhor acao por prioridade: recebivel atrasado, contrato pendente, tarefa atrasada ou relacionamento.
- resumo operacional com projetos, recebiveis, contratos, aniversario, origem e valor.
- linha do tempo consolidada com historico, projetos, tarefas concluidas, recebiveis e contratos.
- projetos vinculados seguem clicaveis e focados na operacao.
- recebiveis e contratos aparecem consolidados dentro do cliente.
- ficha do cliente, registrar interacao e criar projeto ficaram recolhidos, sem dominar a tela.
- campo status do cliente agora e salvo corretamente na edicao.

Validado:
- sintaxe do backend.
- /clientes, /clientes/1, /projetos/1, /tarefas, /recebiveis.
- executavel instalado validado nas rotas principais.

Backup da aplicacao instalada:
- backup_20260501_143339

## 01/05/2026 - Projeto como central de operacao guiada

Entregue:
- topo do projeto mais operacional com etapa atual, prazo, progresso, contrato e recebiveis.
- bloco "Proxima acao do projeto" por prioridade: recebivel atrasado, contrato pendente, tarefa atrasada ou etapa atual.
- etapas redesenhadas como feito, em andamento e proximo, deixando de parecer checklist generico.
- historico util do projeto consolidando agenda, etapas, tarefas, pagamentos e contrato.
- recebiveis do projeto aparecem como leitura operacional, mantendo a gestao central em /recebiveis.
- contrato reorganizado com status, datas, WhatsApp e follow-up.
- resumo do projeto agora salva status e prazo, alem das observacoes.
- pasta viva mantida para links/arquivos sem upload pesado.

Validado:
- /projetos, /projetos/1, /clientes/1, /tarefas, /agenda, /recebiveis e /feedbacks no executavel instalado.

Backup da aplicacao instalada:
- backup_20260501_150651

## 01/05/2026 - Recebiveis como financeiro leve

Entregue:
- topo de recebiveis reforcado com total em aberto, vencendo em breve, atrasado e recebido no mes.
- cards do topo clicaveis por status.
- lista de parcelas mais limpa, com cliente/projeto/parcela, valor, vencimento, status e acoes minimas.
- acoes mantidas simples: WhatsApp e Pago/Reabrir.
- previsao mensal mostra mes atual e respeita o filtro de mes selecionado.
- nova parcela fica recolhida por padrao e abre somente pelo botao.
- formulario de nova parcela ficou compacto com campos essenciais.

Validado:
- /recebiveis
- /recebiveis?mes=2026-05
- /projetos/1
- /clientes/1
- /tarefas
- executavel instalado validado.

Backup da aplicacao instalada:
- backup_20260501_151438

## 01/05/2026 - Agenda operacional

Entregue:
- topo da Agenda reorganizado com Hoje, Atrasados, Proximos e Google Agenda.
- bloco do Google Agenda mais claro, com importacao e reconexao no mesmo lugar.
- calendario mensal mantido como visual principal, com eventos clicaveis.
- novo compromisso saiu do modal pesado e virou painel recolhido de criacao rapida.
- formulario cria compromisso no CRM e pode enviar tambem para o Google Agenda quando conectado.
- cards de compromisso ficaram mais limpos, com acoes minimas: Google, Vincular e Concluir/Reabrir.
- lista de proximos compromissos e concluidos ficou compacta para reduzir poluicao visual.

Validado:
- sintaxe do backend.
- /login
- /
- /clientes
- /projetos
- /leads
- /tarefas
- /feedbacks
- /agenda
- /agenda?ano=2026&mes=5
- /orcamento
- /recebiveis

Backup da aplicacao instalada:
- backup_20260501_152953

## 01/05/2026 - Google Meet automatico na Agenda

Entregue:
- compromissos criados como Google Meet agora solicitam link automatico ao Google Calendar.
- link retornado pelo Google fica salvo no campo de link do compromisso.
- sincronizacao com Google usa conferenceDataVersion para criar sala Meet real.
- eventos ja vinculados ao Google continuam atualizando sem quebrar compatibilidade.

Validado:
- sintaxe do backend.
- geracao do corpo Google com conferenceData hangoutsMeet.
- /agenda
- /agenda?ano=2026&mes=5
- /
- /tarefas
- /clientes
- /projetos
- /recebiveis

Backup da aplicacao instalada:
- backup_20260501_153712

## 01/05/2026 - Edicao de compromissos na Agenda

Entregue:
- card de compromisso ganhou acao Editar.
- modal de edicao permite alterar titulo, data, hora, tipo, formato, cliente, projeto, link, local e observacoes.
- edicao atualiza o compromisso no CRM sem recriar evento.
- quando o compromisso ja esta sincronizado com Google, a alteracao tambem tenta atualizar o Google Agenda.
- formato Google Meet continua podendo gerar ou manter link automatico.

Validado:
- sintaxe do backend.
- /agenda
- /agenda?ano=2026&mes=5
- /
- /tarefas
- /clientes
- /projetos
- /recebiveis

Backup da aplicacao instalada:
- backup_20260501_154838

## 01/05/2026 - Proxima acao a partir da Agenda

Entregue:
- compromissos ganharam botao Acao.
- modal curto cria tarefa a partir do compromisso.
- opcoes rapidas: Enviar proposta, Ajustar layout, Preparar 3D, Cobrar retorno, Agendar proxima reuniao e Registrar decisao.
- tarefa nasce vinculada ao cliente/projeto quando o compromisso tem vinculo.
- tarefa recebe origem agenda e referencia ao compromisso.
- historico do cliente/projeto registra a acao criada.

Validado:
- sintaxe do backend.
- /agenda
- /agenda?ano=2026&mes=5
- /
- /tarefas
- /clientes
- /projetos
- /recebiveis
- criacao de tarefa testada em copia temporaria do data.json instalado.

Backup da aplicacao instalada:
- backup_20260501_162605

## 01/05/2026 - Calendario da Agenda mais operacional

Entregue:
- clique no dia do calendario abre novo compromisso com data preenchida.
- clique no evento do calendario abre resumo rapido sem tirar a usuaria da Agenda.
- resumo rapido oferece Google, abrir vinculo, vincular, editar, criar acao e concluir/reabrir.
- filtros adicionados: Todos, Hoje, Atrasados, Google, Sem vinculo e Concluidos.
- eventos sem vinculo ficam destacados e com chip Vincular.
- lista de compromissos recebe atributos para filtro sem recarregar a pagina.

Validado:
- sintaxe do backend.
- /agenda
- /agenda?ano=2026&mes=5
- /
- /tarefas
- /clientes
- /projetos
- /recebiveis
- /feedbacks

Backup da aplicacao instalada:
- backup_20260501_163459

## 01/05/2026 - Vinculo inteligente da Agenda

Entregue:
- sugestao de vinculo da Agenda ficou mais inteligente, com pontuacao por projeto, cliente, nome, descricao e local.
- eventos sem cliente/projeto mostram sugestao com nivel de confianca.
- card do compromisso ganhou botao Confirmar vinculo quando houver sugestao.
- resumo rapido do calendario tambem permite confirmar a sugestao.
- confirmacao preenche projeto e cliente automaticamente quando a sugestao e de projeto.
- logica de vinculo manual foi consolidada em helper unico para evitar duplicacao.

Validado:
- sintaxe do backend.
- /agenda
- /agenda?ano=2026&mes=5
- /
- /tarefas
- /clientes
- /projetos
- /recebiveis
- /feedbacks
- sugestao e confirmacao testadas em copia temporaria do data.json instalado.

Backup da aplicacao instalada:
- backup_20260501_164250

## 05/05/2026 - Financeiro leve com despesas

Entregue:
- novo módulo Financeiro separado de Recebíveis.
- Recebíveis continuam focados em entradas de clientes/projetos.
- Despesas simples adicionadas com descricao, categoria, valor, vencimento, status, recorrencia e observacao.
- resumo mensal com previsto a receber, previsto a pagar, saldo previsto e saldo realizado.
- filtros de despesas por status, mês e busca.
- ações mínimas para despesas: Pago, Reabrir e Excluir.
- navegacao lateral ganhou item Financeiro.

Validado:
- sintaxe do backend.
- /financeiro
- /financeiro?mes=2026-05
- /recebiveis
- /
- /agenda
- /tarefas
- /clientes
- /projetos
- /feedbacks
- criacao de despesa testada em copia temporaria do data.json instalado.

Backup da aplicacao instalada:
- backup_20260505_204712

## 05/05/2026 - Mesa do Dia e sino operacional

Entregue:
- Mesa do Dia separa Recebiveis, Despesas, Agenda, Tarefas, Leads, Contratos e Clientes.
- fila de prioridade clicavel no Dashboard, com destino direto para o local correto.
- despesas atrasadas ou vencendo entram no sino.
- resumo do sino passou a contar Despesa como categoria propria.
- card do sino continua limpo: clicar na pendencia abre o destino e remove o aviso.
- Recebiveis e Financeiro ficaram conectados sem transformar o CRM em ERP pesado.

Validado:
- sintaxe do backend.
- /
- /financeiro
- /recebiveis
- /agenda
- /tarefas
- /clientes
- /projetos
- /feedbacks
- /orcamento
- despesa atrasada no sino testada em copia temporaria do data.json.

Backup da aplicacao instalada:
- backup_20260505_205704

## 05/05/2026 - Acoes diretas na Mesa do Dia

Entregue:
- itens da Fila de prioridade continuam clicaveis para abrir o contexto completo.
- recebiveis na Mesa do Dia ganharam acao direta Pago.
- despesas na Mesa do Dia ganharam acao direta Pago.
- tarefas e compromissos ganharam acao direta Concluir.
- leads, contratos e relacionamento mantem acao simples Abrir para evitar decisao errada em um clique.
- nenhum endpoint duplicado foi criado; a Mesa reaproveita as rotas estaveis dos modulos.

Validado:
- sintaxe do backend.
- /
- acoes POST testadas em copia temporaria do data.json: pagamento, despesa, tarefa e agenda.

Backup da aplicacao instalada:
- backup_20260505_210155

## 05/05/2026 - Historico automatico de acoes

Entregue:
- helper unico para registrar historico operacional sem duplicar registros.
- tarefas concluidas/reabertas registram historico no cliente/projeto/lead vinculado.
- parcelas pagas/reabertas e lembretes de cobranca registram historico no cliente e projeto.
- leads registram contato, mudanca de etapa, conversao, perda, futuro e reativacao.
- contratos registram mudanca de status e follow-up de assinatura.
- Agenda passou a usar o helper consolidado de historico.

Validado:
- sintaxe do backend.
- acoes de tarefa, parcela e lead testadas em copia temporaria do data.json.
- historico gerado em cliente, projeto e lead sem alterar dados reais.

Backup da aplicacao instalada:
- backup_20260505_211433

## 05/05/2026 - Central de Atividades

Entregue:
- nova rota /atividades.
- item Atividades adicionado ao menu lateral.
- linha do tempo geral com clientes, projetos, leads, tarefas, agenda, recebiveis e contratos.
- filtros por tipo e busca livre.
- resumo superior com total, clientes, projetos e comercial.
- leitura consolidada dos dados existentes sem alterar data.json.

Validado:
- /atividades
- /atividades?tipo=Cliente
- /atividades?q=projeto
- /
- /clientes
- /projetos
- /agenda
- /tarefas
- /financeiro
- /recebiveis

Backup da aplicacao instalada:
- backup_20260505_212355

## Regua viva de maturidade do produto

Atualizar estes percentuais ao fim de cada bloco relevante de produto:

- Motion conceitual: 47%
- CRM autoral da Vitoria: 76%
- Produto maduro comercializavel: 57%

Leitura atual:
- O CRM avancou no conceito Motion com proxima melhor acao, prioridade do dia, acoes diretas, Tarefas mais legiveis, Leads V2 e Recebiveis V2 em teste real.
- O diferencial autoral continua forte porque o fluxo conversa com arquitetura/interiores, relacionamento, cobranca amigavel e projeto.
- Ainda falta maturidade comercial: resolver empacotamento PyInstaller, Recebiveis V2, planejamento semanal e revisao visual fina com uso real da Vitoria.

## 07/05/2026 - Polimento visual de Tarefas e Dashboard

Entregue:
- sidebar estabilizada com icones ASCII para evitar quebra visual no Windows empacotado.
- todos os links da barra lateral revisados e validados.
- Tarefas ajustada para priorizar leitura larga em vez de colunas espremidas.
- cards de tarefa agora preservam largura do titulo, contexto e motivo da automacao.
- acoes de tarefa ficaram compactas, sem roubar espaco do texto.
- Dashboard recebeu ajuste de largura no painel Resultado de hoje e melhor comportamento responsivo.

Validado:
- encoding UTF-8 dos arquivos alterados.
- /, /tarefas, /leads, /projetos, /clientes, /agenda, /recebiveis, /atividades, /financeiro e /feedbacks.
- CSS instalado servido pelo app real com os novos seletores.
- app instalado atualizado com backup e mantido aberto para teste.

Backup da aplicacao instalada:
- backup_20260507_234409

## 09/05/2026 - Recuperacao do exe e Leads V2 em modo seguro

Entregue:
- identificado que o PyInstaller travou e o exe empacotado ficou abrindo processo sem subir servidor local.
- parado servidor temporario e multiplas instancias do exe para limpar conflito de porta.
- criado launcher seguro `CRM Vitoria Uardon.exe` em C# para abrir o CRM pela base-fonte, usando os dados reais instalados.
- dados reais continuam apontando para a pasta instalada:
  - `data.json`
  - `uploads`
  - `google_credentials.json`
  - `google_token.json`
- Leads V2 ficou disponivel para teste real com bloco Comercial agora, proxima acao e metricas de esteira.

Validado:
- `/`
- `/leads`
- `/tarefas`
- `/clientes`
- `/projetos`
- `/agenda`
- `/recebiveis`
- `/atividades`
- `/financeiro`
- `/feedbacks`
- `/orcamento`
- sem caracteres corrompidos.

Backup da aplicacao instalada:
- backup_20260509_103535_safe_launcher

Observacao tecnica:
- esta e uma solucao segura de continuidade, nao a solucao final de empacotamento.
- proximo passo tecnico: corrigir o build PyInstaller sem travamento e voltar para pacote autocontido.

## 09/05/2026 - Recebiveis V2 como cobranca amigavel

Entregue:
- Recebiveis ganhou bloco "Cobranca agora" no topo.
- a tela passa a sugerir a parcela mais importante para tratar primeiro.
- prioridade respeita atraso, vencimento em breve e parcelas abertas.
- acoes diretas mantidas simples: WhatsApp, Pago e Abrir projeto.
- a tela continua sendo financeiro leve, sem virar ERP.

Validado:
- `/recebiveis`
- `/`
- `/leads`
- `/tarefas`
- `/clientes`
- `/projetos`
- `/agenda`
- `/financeiro`
- `/atividades`
- `/feedbacks`
- sem caracteres corrompidos.

Observacao:
- validado no modo atual de continuidade, com o launcher seguro apontando para a base-fonte e dados reais instalados.
