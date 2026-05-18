# CRM Vitória Uardon - Base-fonte

Esta pasta é a base-fonte oficial para evoluir o CRM antes de gerar um novo `.exe`.

Princípios:
- preservar compatibilidade com `data.json`;
- n�o sobrescrever `uploads`;
- desenvolver aqui, empacotar depois;
- laptop da Vit�ria continua sendo ambiente de uso real, n�o de experimenta��o.

Variáveis úteis:
- `CRM_DATA_FILE`: caminho do `data.json` usado pelo app;
- `CRM_UPLOAD_DIR`: caminho da pasta `uploads`;
- `PORT`: porta local do Flask.

Próximo marco técnico:
- instalar dependências em ambiente controlado;
- validar rotas principais;
- empacotar novo `.exe` a partir deste fonte;
- aplicar update pelo script oficial com backup automático.
