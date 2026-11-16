"""Prompts e schemas de saída de cada tarefa de IA (v1).

Todos pedem JSON com schema explícito (`responseJsonSchema`): o fluxo valida campos obrigatórios
e trata resposta inválida como "erro_llm" com revisão humana.
"""

S = {"type": "string"}
S_NULL = {"type": ["string", "null"]}

TASKS = {
    "email": {
        "system": """Tarefa: triagem_email
Você faz a triagem da caixa de entrada de uma pequena empresa.
- Classifique a categoria e a prioridade. Alta = cliente insatisfeito, prazo em até 2 dias, risco financeiro ou legal.
- `resumo`: uma frase. `acao_sugerida`: o próximo passo concreto.
- `valores_mencionados`: valores em reais citados no e-mail (números), sem inventar.
- `rascunho_resposta`: resposta curta, educada e em português; null para spam.
- `confianca`: de 0 a 1, quão claro está o e-mail. Seja honesto: e-mail ambíguo tem confiança baixa.""",
        "schema": {"type": "object", "properties": {
            "categoria": {"type": "string", "enum": ["cliente_reclamacao", "cliente_duvida", "fornecedor_cobranca",
                                                     "fornecedor_proposta", "interno", "spam", "outro"]},
            "prioridade": {"type": "string", "enum": ["alta", "media", "baixa"]},
            "resumo": S, "acao_sugerida": S, "prazo_mencionado": S_NULL,
            "valores_mencionados": {"type": "array", "items": {"type": "number"}},
            "rascunho_resposta": S_NULL, "confianca": {"type": "number", "minimum": 0, "maximum": 1}},
            "required": ["categoria", "prioridade", "resumo", "acao_sugerida", "confianca"]},
    },
    "documento": {
        "system": """Tarefa: processamento_documento
Você classifica documentos de uma pequena empresa e extrai os campos importantes.
- `tipo`: nota_fiscal, boleto, contrato, curriculo ou outro.
- `campos`: lista de {campo, valor} com nomes em snake_case (ex.: numero, cnpj, valor_total, vencimento, partes, vigencia).
  Copie os valores como estão no texto; não invente campos ausentes.
- `pontos_de_atencao`: multas, prazos, renovações automáticas, inconsistências.
- `resumo`: uma frase.""",
        "schema": {"type": "object", "properties": {
            "tipo": {"type": "string", "enum": ["nota_fiscal", "boleto", "contrato", "curriculo", "outro"]},
            "campos": {"type": "array", "items": {"type": "object", "properties": {"campo": S, "valor": S},
                                                  "required": ["campo", "valor"]}},
            "pontos_de_atencao": {"type": "array", "items": S}, "resumo": S},
            "required": ["tipo", "campos", "resumo"]},
    },
    "reuniao": {
        "system": """Tarefa: ata_reuniao
Você transforma a transcrição de uma reunião em ata objetiva.
- `decisoes`: só o que foi de fato decidido (não sugestões).
- `tarefas`: cada uma com responsável (use exatamente o nome de um participante; null se ninguém assumiu) e prazo (como foi dito; null se não houve).
- `riscos`: preocupações levantadas que ficaram em aberto.
- Não invente decisões, tarefas ou prazos que não estão na transcrição.""",
        "schema": {"type": "object", "properties": {
            "resumo": S, "decisoes": {"type": "array", "items": S},
            "tarefas": {"type": "array", "items": {"type": "object", "properties": {
                "descricao": S, "responsavel": S_NULL, "prazo": S_NULL}, "required": ["descricao"]}},
            "riscos": {"type": "array", "items": S}, "proxima_reuniao": S_NULL},
            "required": ["resumo", "decisoes", "tarefas"]},
    },
    "pesquisa": {
        "system": """Tarefa: pesquisa_com_fontes
Você escreve um resumo de pesquisa usando SOMENTE as fontes numeradas fornecidas.
- `resumo`: 3 a 5 frases.
- `pontos_chave`: cada ponto cita os números das fontes que o sustentam em `fontes`.
- `lacunas`: o que o tema pede e as fontes não cobrem.
- Não use conhecimento externo. Se as fontes divergirem, diga isso.""",
        "schema": {"type": "object", "properties": {
            "resumo": S, "pontos_chave": {"type": "array", "items": {"type": "object", "properties": {
                "texto": S, "fontes": {"type": "array", "items": {"type": "integer"}}},
                "required": ["texto", "fontes"]}},
            "lacunas": {"type": "array", "items": S}},
            "required": ["resumo", "pontos_chave"]},
    },
    "relatorio": {
        "system": """Tarefa: relatorio_indicador
Você escreve um boletim curto sobre o indicador recebido, para o dono de uma pequena empresa.
- Use SOMENTE os números fornecidos, com vírgula decimal e as mesmas casas decimais. Não calcule nada novo.
- `titulo`: até 8 palavras. `resumo`: 2 frases. `destaques`: 2 ou 3 bullets.
- Sem recomendação de investimento.""",
        "schema": {"type": "object", "properties": {
            "titulo": S, "resumo": S, "destaques": {"type": "array", "items": S}},
            "required": ["titulo", "resumo", "destaques"]},
    },
}
