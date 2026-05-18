# Contexto de Continuidade - CRM Vitoria Uardon

Atualizado em: 01/05/2026

## Projeto

Aplicacao Flask local chamada "CRM Vitoria Uardon", usada no laptop da Vitoria. A base-fonte oficial fica em `crm_vitoria_source`.

Arquivos importantes:
- `app.py`: rotas, regras de negocio, persistencia em JSON e automacoes.
- `templates/`: telas HTML do CRM.
- `static/style.css`: estilo visual.
- `data.example.json`: exemplo de estrutura de dados.
- `REGISTRO_PRODUTO.md`: historico e estado do produto.
- `ROADMAP_AUTOMACOES_PRODUTO/`: planejamento das proximas automacoes.
- `dist/CRM Vitoria Uardon/`: build gerado com PyInstaller.

Dependencias principais:
- Flask 2.3.3
- Werkzeug 3.1.3

## Regra de Ouro

Ao atualizar o CRM instalado no laptop da Vitoria, nunca substituir:
- `data.json`
- `uploads`

Substituir somente:
- `CRM Vitoria Uardon.exe`
- `_internal`

O app deve preservar compatibilidade com dados reais.

## Estado Atual

O CRM ja possui:
- login por usuario/e-mail;
- dashboard;
- clientes;
- projetos;
- leads;
- tarefas;
- feedbacks;
- agenda;
- financeiro/recebiveis;
- biblioteca de modelos;
- formulario publico local em `/orcamento`;
- build `.exe` gerado com PyInstaller.

Formulario `/orcamento`:
- grava o envio como lead;
- define `origem` como `Instagram`;
- define `etapa` como `Orcamento recebido`;
- define `status` como `Novo`;
- cria uma tarefa automatica "Responder orcamento recebido";
- mostra pagina de obrigado apos envio.

Dashboard:
- carrega tarefas e eventos do dia;
- mostra leads de orcamento vindos do Instagram;
- executa `ensure_lead_followup_tasks(data)` para gerar follow-up de leads parados.

Leads:
- possuem esteira/pipeline;
- tem destaque para leads sem avanco;
- podem abrir WhatsApp Web;
- podem ser movidos para futuro ou marcados como perdidos.

Notificacoes:
- existe `build_notifications(data)`;
- existe lista `dismissed_notifications`;
- existe sino/menu de notificacoes no layout;
- ainda falta confirmar se ha um helper separado `create_notification`, pois o roadmap ainda marca isso como pendente.

## Proxima Implementacao Recomendada

Finalizar a primeira versao do motor de automacoes.

Checklist atual do roadmap:
- [ ] Criar helper `create_notification`.
- [x] Criar helper para gerar tarefa automatica de lead.
- [x] Criar helper para evitar duplicidade.
- [x] Ao receber `/orcamento`, criar tarefa "Responder orcamento".
- [x] Mostrar no dashboard bloco "Novos orcamentos".
- [x] Em Leads, destacar etapa "Orcamento recebido".
- [x] Botao de WhatsApp Web no lead.
- [ ] Validar rotas principais.
- [ ] Gerar novo `.exe`.
- [ ] Aplicar update preservando `data.json` e `uploads`.

## Como Continuar

Se a conversa compactar ou for aberta uma nova, pedir:

> Leia `crm_vitoria_source/CONTEXTO_CONTINUIDADE.md`, `REGISTRO_PRODUTO.md` e `ROADMAP_AUTOMACOES_PRODUTO/04_PROXIMA_IMPLEMENTACAO.md`. Depois continue a implementacao do motor de automacoes do CRM, preservando `data.json` e `uploads`.

Ordem segura de trabalho:
1. Ler `app.py` e confirmar os helpers existentes.
2. Implementar ou consolidar `create_notification`.
3. Validar `/orcamento`, dashboard, leads, tarefas e sino.
4. Rodar o app localmente com uma copia de dados.
5. Gerar novo `.exe` somente depois de validar.
6. Atualizar a instalacao real preservando `data.json` e `uploads`.

## Observacoes Tecnicas

Alguns arquivos aparecem com texto mojibake em leituras pelo terminal, por exemplo `Orçamento` em vez de `Orcamento`. Existem scripts em `tools/` para corrigir mojibake, mas qualquer correcao de encoding deve ser feita com cuidado e validada, porque o app ja tem dados reais.

O comando `git` nao esta disponivel neste ambiente atual, entao nao foi possivel consultar status de versionamento.
