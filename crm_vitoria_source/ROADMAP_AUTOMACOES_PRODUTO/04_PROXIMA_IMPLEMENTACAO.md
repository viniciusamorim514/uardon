# Proxima Implementacao Recomendada

## Escopo

Implementar a primeira versao do motor de automacoes.

## Por Que Agora

A pagina `/orcamento` ja existe.

Sem automacao, ela apenas grava lead.

Com automacao, ela vira rotina comercial:

- lead chega;
- sino avisa;
- tarefa e criada;
- WhatsApp e sugerido;
- dashboard mostra prioridade.

## Entregas Da Proxima Rodada

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

## Criterio de Pronto

A Vitoria recebe um orcamento pelo formulario e o CRM automaticamente:

- grava o lead;
- mostra no sino;
- cria uma tarefa de resposta;
- permite chamar no WhatsApp Web;
- mostra o novo orcamento no dashboard.
