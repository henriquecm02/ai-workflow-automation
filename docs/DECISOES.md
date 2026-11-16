# Decisões de projeto

## 1. Workflows gerados por código

Os JSON em `workflows/` são gerados por `build.py`. Editar à mão cinco cópias da mesma cadeia de IA (montar requisição, chamar o modelo, validar) leva a divergências: um fluxo ganha retentativas e outro não, um trata JSON inválido e outro quebra. Gerando, a cadeia existe uma vez. Prompts e schemas ficam em Python legível e versionado (`prompts.py`), em vez de dentro de strings escapadas no JSON.

**Custo:** quem edita um fluxo no editor visual do n8n precisa trazer a mudança de volta para `build.py`, ou ela se perde na próxima geração.

## 2. HTTP Request em vez do nó nativo de LLM

O n8n tem nós prontos para modelos de linguagem. Usei o nó HTTP chamando a API REST do Gemini porque:

- o formato da requisição fica explícito e testável (o servidor falso valida o mesmo contrato);
- dá para trocar a URL base por variável de ambiente e testar sem chave;
- a saída estruturada (`responseJsonSchema`) é controlada diretamente.

**Custo:** trocar de provedor exige ajustar o nó de montagem e o de validação.

## 3. A IA interpreta, regras em código decidem

O modelo classifica, extrai e resume. O que acontece depois (para onde o e-mail vai, se o documento é arquivado, se a tarefa tem responsável válido) é decidido em nós de código, com regras explícitas. Assim o comportamento crítico é auditável e não muda quando o modelo muda.

## 4. Falha do modelo não quebra o fluxo

Resposta que não é JSON, campo obrigatório ausente ou erro da API viram `status: "erro_llm"` e o item segue para revisão humana. O nó do Gemini usa `onError: continueRegularOutput` e 3 tentativas.

## 5. Chave por variável de ambiente

A chave entra via `$env.GEMINI_API_KEY` (com `N8N_BLOCK_ENV_ACCESS_IN_NODE=false`). Isso permite subir o ambiente com `docker compose` sem passos manuais no editor e trocar a URL para o servidor de teste.

**Custo e alternativa:** qualquer nó de código do n8n consegue ler variáveis de ambiente. Em um n8n compartilhado, o correto é usar uma credencial *Header Auth* (cofre criptografado do n8n) e manter o bloqueio de `$env` ativo. Está no roadmap.

## 6. Pesquisa só com fontes recuperadas

O fluxo de pesquisa entrega as fontes numeradas ao modelo e exige que cada ponto cite pelo menos uma delas. Citações para números de fonte inexistentes são removidas e contadas (`citacoes_invalidas`), e pontos que ficam sem fonte aparecem marcados no relatório.
