"""Gera os workflows do n8n (JSON importável) a partir de definições em Python.

Por que gerar em vez de editar o JSON à mão: os 5 fluxos compartilham a mesma cadeia de IA
(montar requisição -> chamar o Gemini -> validar a resposta). Gerando, a cadeia é escrita uma vez,
os prompts e schemas ficam legíveis em `prompts.py` e uma mudança vale para todos os fluxos.

  python workflows/build.py      # reescreve workflows/*.json
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from prompts import TASKS

OUT = Path(__file__).parent
NS = uuid.UUID("6f1c9a52-6a1e-4d39-9a43-0c3f6c9f2b10")

GEMINI_URL = ("={{ ($env.GEMINI_BASE_URL || 'https://generativelanguage.googleapis.com') + "
              "'/v1beta/models/' + ($env.GEMINI_MODEL || 'gemini-3.8-flash') + ':generateContent' }}")


class WF:
    def __init__(self, slug: str, name: str):
        self.slug, self.name = slug, name
        self.nodes: list[dict] = []
        self.conn: dict[str, dict] = {}
        self.x = 0

    def node(self, name: str, type_: str, version: float, params: dict, y: int = 300, **extra) -> str:
        self.x += 240
        n = {"id": str(uuid.uuid5(NS, f"{self.slug}/{name}")), "name": name, "type": type_,
             "typeVersion": version, "position": [self.x, y], "parameters": params, **extra}
        self.nodes.append(n)
        return name

    def link(self, a: str, b: str, out: int = 0) -> None:
        outs = self.conn.setdefault(a, {"main": []})["main"]
        while len(outs) <= out:
            outs.append([])
        outs[out].append({"node": b, "type": "main", "index": 0})

    def chain(self, *names: str) -> str:
        for a, b in zip(names, names[1:]):
            self.link(a, b)
        return names[-1]

    # ---- blocos reutilizáveis -------------------------------------------------------------
    def webhook(self, path: str) -> str:
        return self.node("Webhook", "n8n-nodes-base.webhook", 2,
                         {"httpMethod": "POST", "path": path, "responseMode": "lastNode",
                          "responseData": "firstEntryJson", "options": {}},
                         webhookId=str(uuid.uuid5(NS, f"{self.slug}/webhook")))

    def code(self, name: str, js: str, y: int = 300) -> str:
        return self.node(name, "n8n-nodes-base.code", 2, {"jsCode": js.strip()}, y=y)

    def http_get(self, name: str, url: str, query: dict[str, str]) -> str:
        return self.node(name, "n8n-nodes-base.httpRequest", 4.2, {
            "method": "GET", "url": url, "sendQuery": True,
            "queryParameters": {"parameters": [{"name": k, "value": v} for k, v in query.items()]},
            "sendHeaders": True,
            "headerParameters": {"parameters": [{"name": "User-Agent",
                                                 "value": "ai-workflow-automation/0.1 (portfolio)"}]},
            "options": {"timeout": 30000}}, retryOnFail=True, maxTries=3, waitBetweenTries=2000)

    def llm(self, task: str, prompt_expr: str) -> tuple[str, str]:
        """Cadeia de IA: monta requisição -> Gemini -> valida JSON. Retorna (primeiro, último) nó."""
        t = TASKS[task]
        build = self.code("IA · montar requisição", f"""
const tarefa = {json.dumps(t['system'], ensure_ascii=False)};
const schema = {json.dumps(t['schema'], ensure_ascii=False)};
const entrada = {prompt_expr};
return [{{ json: {{ ...$json, request: {{
  systemInstruction: {{ parts: [{{ text: tarefa }}] }},
  contents: [{{ role: 'user', parts: [{{ text: entrada }}] }}],
  generationConfig: {{ temperature: 0, responseMimeType: 'application/json', responseJsonSchema: schema }}
}} }} }}];
""")
        call = self.node("IA · Gemini", "n8n-nodes-base.httpRequest", 4.2, {
            "method": "POST", "url": GEMINI_URL, "sendHeaders": True,
            "headerParameters": {"parameters": [{"name": "x-goog-api-key", "value": "={{ $env.GEMINI_API_KEY }}"}]},
            "sendBody": True, "specifyBody": "json", "jsonBody": "={{ JSON.stringify($json.request) }}",
            "options": {"timeout": 90000}},
            retryOnFail=True, maxTries=3, waitBetweenTries=3000, onError="continueRegularOutput")
        required = json.dumps(t["schema"].get("required", []))
        parse = self.code("IA · validar resposta", f"""
// Resposta do Gemini -> objeto. Qualquer falha vira status "erro_llm" com revisão humana,
// em vez de quebrar o fluxo ou seguir com dado inválido.
const r = $json;
const texto = r?.candidates?.[0]?.content?.parts?.map(p => p.text || '').join('') || '';
let dados = null, erro = r?.error ? JSON.stringify(r.error).slice(0, 300) : null;
if (!erro) {{
  try {{ dados = JSON.parse(texto); }} catch (e) {{ erro = 'JSON inválido do modelo: ' + texto.slice(0, 200); }}
}}
const faltando = dados ? {required}.filter(k => !(k in dados)) : [];
if (faltando.length) erro = 'Campos obrigatórios ausentes: ' + faltando.join(', ');
const uso = r?.usageMetadata || {{}};
return [{{ json: {{
  status: erro ? 'erro_llm' : 'ok', erro, dados,
  tokens: (uso.promptTokenCount || 0) + (uso.candidatesTokenCount || 0) + (uso.thoughtsTokenCount || 0),
}} }}];
""")
        self.chain(build, call, parse)
        return build, parse

    def to_json(self) -> dict:
        return {"id": self.slug.replace("-", "")[:16], "name": self.name, "active": True, "nodes": self.nodes,
                "connections": self.conn, "settings": {"executionOrder": "v1"}, "pinData": {},
                "tags": [], "meta": {"templateCredsSetupCompleted": True}}


# =============================================================================== workflows

def email_intelligence() -> WF:
    w = WF("email-intelligence", "01 · Email Intelligence")
    hook = w.webhook("email-intelligence")
    prep = w.code("Preparar e-mail", """
const b = $json.body || {};
if (!b.corpo || !b.assunto) throw new Error('Campos obrigatórios: assunto, corpo');
return [{ json: { de: b.de || '', assunto: String(b.assunto).slice(0, 300),
  corpo: String(b.corpo).slice(0, 8000), recebido_em: b.recebido_em || new Date().toISOString() } }];
""")
    first, parse = w.llm("email", "`De: ${$json.de}\\nAssunto: ${$json.assunto}\\n\\n${$json.corpo}`")
    route = w.code("Aplicar regras", """
const email = $('Preparar e-mail').first().json;
const ia = $json;
if (ia.status !== 'ok') return [{ json: { email, fila: 'revisao_humana', revisao_humana: true, motivo: ia.erro } }];
const d = ia.dados;
// Regras em código, não no prompt: confiança baixa ou dinheiro envolvido -> humano revisa.
const revisao = d.confianca < 0.6 || (d.valores_mencionados || []).length > 0 && d.categoria === 'fornecedor_cobranca';
const fila = d.categoria === 'spam' ? 'arquivar' : revisao ? 'revisao_humana' : d.prioridade === 'alta' ? 'urgente' : 'normal';
return [{ json: { email: { de: email.de, assunto: email.assunto }, fila, revisao_humana: revisao,
  classificacao: d, rascunho_resposta: d.categoria === 'spam' ? null : d.rascunho_resposta, tokens: ia.tokens } }];
""")
    sw = w.node("Fila", "n8n-nodes-base.switch", 3.2, {
        "rules": {"values": [
            {"conditions": {"options": {"caseSensitive": True, "typeValidation": "strict", "version": 2},
                            "combinator": "and", "conditions": [{"leftValue": "={{ $json.fila }}",
                                                                 "rightValue": v, "operator": {"type": "string",
                                                                                               "operation": "equals"}}]},
             "renameOutput": True, "outputKey": v} for v in ("urgente", "normal", "arquivar", "revisao_humana")]},
        "options": {}})
    actions = {
        "urgente": "notificar o responsável agora (Slack/Telegram)",
        "normal": "aplicar rótulo e incluir no resumo diário",
        "arquivar": "mover para a pasta de spam",
        "revisao_humana": "enviar para a fila de revisão humana",
    }
    w.chain(hook, prep, first)
    w.chain(parse, route, sw)
    for i, (k, v) in enumerate(actions.items()):
        n = w.code(f"Ação · {k}", f"""
// Em produção este nó seria a integração real (Gmail/Slack). Aqui registra a ação decidida.
return [{{ json: {{ ...$json, acao: {json.dumps(v, ensure_ascii=False)}, modo: 'demonstracao' }} }}];
""", y=120 + 140 * i)
        w.link(sw, n, out=i)
    return w


def document_processing() -> WF:
    w = WF("document-processing", "02 · Document Processing")
    hook = w.webhook("document-processing")
    prep = w.code("Preparar documento", """
const b = $json.body || {};
if (!b.texto) throw new Error('Campo obrigatório: texto (conteúdo extraído do arquivo)');
return [{ json: { arquivo: b.arquivo || 'sem_nome', texto: String(b.texto).slice(0, 15000) } }];
""")
    first, parse = w.llm("documento", "`Arquivo: ${$json.arquivo}\\n\\n${$json.texto}`")
    post = w.code("Validar e organizar", """
const doc = $('Preparar documento').first().json;
if ($json.status !== 'ok') return [{ json: { arquivo: doc.arquivo, status: 'erro_llm', erro: $json.erro, pasta: 'revisao_humana' } }];
const d = $json.dados;
const campos = Object.fromEntries((d.campos || []).map(c => [c.campo, c.valor]));
const problemas = [];
const cnpj = campos.cnpj || campos.cnpj_emitente;
if (cnpj && !/^\\d{2}\\.\\d{3}\\.\\d{3}\\/\\d{4}-\\d{2}$/.test(cnpj)) problemas.push('cnpj_formato_invalido');
if (d.tipo === 'nota_fiscal' && !campos.valor_total) problemas.push('valor_total_ausente');
const pasta = problemas.length ? 'revisao_humana' : ({ nota_fiscal: 'financeiro/notas', boleto: 'financeiro/boletos',
  contrato: 'juridico/contratos', curriculo: 'rh/curriculos' }[d.tipo] || 'outros');
return [{ json: { arquivo: doc.arquivo, status: 'ok', tipo: d.tipo, pasta, campos, resumo: d.resumo,
  pontos_de_atencao: d.pontos_de_atencao, problemas, tokens: $json.tokens } }];
""")
    w.chain(hook, prep, first)
    w.chain(parse, post)
    return w


def meeting_intelligence() -> WF:
    w = WF("meeting-intelligence", "03 · Meeting Intelligence")
    hook = w.webhook("meeting-intelligence")
    prep = w.code("Preparar transcrição", """
const b = $json.body || {};
if (!b.transcricao) throw new Error('Campo obrigatório: transcricao');
return [{ json: { titulo: b.titulo || 'Reunião', participantes: b.participantes || [],
  transcricao: String(b.transcricao).slice(0, 30000) } }];
""")
    first, parse = w.llm("reuniao", "`Reunião: ${$json.titulo}\\nParticipantes: ${$json.participantes.join(', ')}"
                                    "\\n\\nTranscrição:\\n${$json.transcricao}`")
    post = w.code("Montar ata e follow-up", """
const r = $('Preparar transcrição').first().json;
if ($json.status !== 'ok') return [{ json: { status: 'erro_llm', erro: $json.erro } }];
const d = $json.dados;
const nomes = new Set(r.participantes.map(p => p.toLowerCase()));
// O modelo pode atribuir tarefa a alguém que não estava na reunião: marcamos em vez de aceitar.
const tarefas = (d.tarefas || []).map(t => ({ ...t,
  responsavel_valido: !!t.responsavel && nomes.has(t.responsavel.toLowerCase()),
  responsavel: t.responsavel && nomes.has(t.responsavel.toLowerCase()) ? t.responsavel : 'a definir' }));
const md = [`# Ata · ${r.titulo}`, '', d.resumo, '', '## Decisões', ...(d.decisoes || []).map(x => `- ${x}`),
  '', '## Tarefas', '| Tarefa | Responsável | Prazo |', '|---|---|---|',
  ...tarefas.map(t => `| ${t.descricao} | ${t.responsavel} | ${t.prazo || 'sem prazo'} |`),
  ...(d.riscos?.length ? ['', '## Riscos', ...d.riscos.map(x => `- ${x}`)] : [])].join('\\n');
return [{ json: { status: 'ok', titulo: r.titulo, ata_markdown: md, tarefas, decisoes: d.decisoes,
  tarefas_sem_responsavel: tarefas.filter(t => !t.responsavel_valido).length, tokens: $json.tokens } }];
""")
    w.chain(hook, prep, first)
    w.chain(parse, post)
    return w


def research_automation() -> WF:
    w = WF("research-automation", "04 · Research Automation")
    hook = w.webhook("research")
    prep = w.code("Preparar tema", """
const b = $json.body || {};
if (!b.tema) throw new Error('Campo obrigatório: tema');
return [{ json: { tema: String(b.tema).slice(0, 200), max_fontes: Math.min(Number(b.max_fontes) || 3, 5) } }];
""")
    search = w.http_get("Wikipedia · buscar", "https://pt.wikipedia.org/w/api.php", {
        "action": "query", "list": "search", "format": "json", "srsearch": "={{ $json.tema }}",
        "srlimit": "={{ $json.max_fontes }}"})
    titles = w.code("Selecionar fontes", """
const hits = $json?.query?.search || [];
if (!hits.length) throw new Error('Nenhuma fonte encontrada para o tema');
return [{ json: { titulos: hits.map(h => h.title).join('|') } }];
""")
    fetch = w.http_get("Wikipedia · ler", "https://pt.wikipedia.org/w/api.php", {
        "action": "query", "prop": "extracts", "explaintext": "1", "exintro": "1", "format": "json",
        "redirects": "1", "titles": "={{ $json.titulos }}"})
    sources = w.code("Organizar fontes", """
const pages = Object.values($json?.query?.pages || {}).filter(p => p.extract);
const fontes = pages.map((p, i) => ({ id: i + 1, titulo: p.title,
  url: 'https://pt.wikipedia.org/wiki/' + encodeURIComponent(p.title.replace(/ /g, '_')),
  texto: p.extract.slice(0, 4000) }));
return [{ json: { tema: $('Preparar tema').first().json.tema, fontes } }];
""")
    first, parse = w.llm("pesquisa", "`Tema: ${$json.tema}\\n\\n` + $json.fontes.map(f => "
                                     "`[${f.id}] ${f.titulo}\\n${f.texto}`).join('\\n\\n')")
    post = w.code("Montar relatório", """
const src = $('Organizar fontes').first().json;
if ($json.status !== 'ok') return [{ json: { status: 'erro_llm', erro: $json.erro, fontes: src.fontes.map(({texto, ...f}) => f) } }];
const d = $json.dados;
const ids = new Set(src.fontes.map(f => f.id));
// Cada ponto precisa citar fonte existente; citação inventada é removida e contabilizada.
let citacoes_invalidas = 0;
const pontos = (d.pontos_chave || []).map(p => {
  const ok = (p.fontes || []).filter(i => ids.has(i));
  citacoes_invalidas += (p.fontes || []).length - ok.length;
  return { ...p, fontes: ok };
});
const md = [`# ${src.tema}`, '', d.resumo, '', '## Pontos-chave',
  ...pontos.map(p => p.fontes.length ? `- ${p.texto} ${p.fontes.map(i => `[${i}]`).join('')}` : `- ⚠️ ${p.texto} _(sem fonte válida: confira antes de usar)_`),
  ...(d.lacunas?.length ? ['', '## O que as fontes não cobrem', ...d.lacunas.map(x => `- ${x}`)] : []),
  '', '## Fontes', ...src.fontes.map(f => `${f.id}. [${f.titulo}](${f.url})`)].join('\\n');
return [{ json: { status: 'ok', tema: src.tema, relatorio_markdown: md, pontos_sem_fonte: pontos.filter(p => !p.fontes.length).length,
  citacoes_invalidas, fontes: src.fontes.map(({ texto, ...f }) => f), tokens: $json.tokens } }];
""")
    w.chain(hook, prep, search, titles, fetch, sources, first)
    w.chain(parse, post)
    return w


def data_reporting() -> WF:
    w = WF("data-reporting", "05 · Data Reporting")
    sched = w.node("Agendamento (dias úteis 19h)", "n8n-nodes-base.scheduleTrigger", 1.2, {
        "rule": {"interval": [{"field": "cronExpression", "expression": "0 19 * * 1-5"}]}}, y=180)
    w.x -= 240
    hook = w.webhook("data-report")
    period = w.code("Definir período", """
const fim = new Date(); const ini = new Date(fim.getTime() - 45 * 864e5);
const f = d => d.toLocaleDateString('pt-BR', { timeZone: 'America/Sao_Paulo' });
return [{ json: { dataInicial: f(ini), dataFinal: f(fim) } }];
""")
    bcb = w.http_get("BCB · dólar PTAX", "https://api.bcb.gov.br/dados/serie/bcdata.sgs.1/dados", {
        "formato": "json", "dataInicial": "={{ $json.dataInicial }}", "dataFinal": "={{ $json.dataFinal }}"})
    stats = w.code("Calcular indicadores", """
const rows = $input.all().map(i => i.json).filter(r => r.data && r.valor)
  .map(r => ({ data: r.data, valor: Number(r.valor) }));
if (rows.length < 8) throw new Error('Poucos dados retornados pela API: ' + rows.length);
const last = rows.at(-1), v = rows.map(r => r.valor);
const pct = (a, b) => Math.round((a / b - 1) * 10000) / 100;
const back = n => rows[Math.max(0, rows.length - 1 - n)].valor;
return [{ json: { indicador: 'Dólar PTAX (venda)', ultima_data: last.data, ultimo: last.valor,
  var_5_pregoes_pct: pct(last.valor, back(5)), var_periodo_pct: pct(last.valor, rows[0].valor),
  minimo: Math.min(...v), maximo: Math.max(...v), observacoes: rows.length, primeira_data: rows[0].data } }];
""")
    first, parse = w.llm("relatorio", "'Indicadores calculados (fonte única de números):\\n' + JSON.stringify($json)")
    post = w.code("Conferir números e publicar", """
const ind = $('Calcular indicadores').first().json;
if ($json.status !== 'ok') return [{ json: { status: 'erro_llm', erro: $json.erro, indicadores: ind } }];
const d = $json.dados;
const texto = [d.titulo, d.resumo, ...(d.destaques || [])].join(' ');
// Mesmo princípio dos outros projetos: número no texto precisa existir nos indicadores.
const permitidos = Object.values(ind).filter(x => typeof x === 'number').map(x => Math.round(Math.abs(x) * 100) / 100);
const citados = [...texto.matchAll(/(\\d+(?:\\.\\d{3})*,\\d+)/g)].map(m => Number(m[1].replace(/\\./g, '').replace(',', '.')));
const sem_respaldo = citados.filter(n => !permitidos.some(p => Math.abs(p - n) < 0.005));
const md = [`# ${d.titulo}`, '', d.resumo, '', ...(d.destaques || []).map(x => `- ${x}`), '',
  `_Fonte: Banco Central do Brasil (SGS), ${ind.primeira_data} a ${ind.ultima_data}._`].join('\\n');
return [{ json: { status: sem_respaldo.length ? 'revisar' : 'ok', relatorio_markdown: md, indicadores: ind,
  numeros_sem_respaldo: sem_respaldo, tokens: $json.tokens,
  entrega: 'em produção: e-mail/Slack para a equipe (modo demonstração: só retorna o relatório)' } }];
""")
    w.link(sched, period)
    w.chain(hook, period, bcb, stats, first)
    w.chain(parse, post)
    return w


BUILDERS = [email_intelligence, document_processing, meeting_intelligence, research_automation, data_reporting]

if __name__ == "__main__":
    for i, b in enumerate(BUILDERS, 1):
        wf = b()
        path = OUT / f"{i:02d}_{wf.slug.replace('-', '_')}.json"
        path.write_text(json.dumps(wf.to_json(), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{path.name}: {len(wf.nodes)} nós")
