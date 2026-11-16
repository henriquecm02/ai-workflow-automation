"""Teste de ponta a ponta dos 5 workflows no n8n real, com o Gemini substituído por um servidor falso.

  python tests/e2e.py            # sobe n8n + mock, roda os casos, derruba tudo
  python tests/e2e.py --manter   # deixa os containers no ar ao final

O que é real: n8n 2.47.7, todos os nós, as APIs da Wikipedia e do Banco Central.
O que é simulado: as respostas do LLM (mock_llm/fixtures). Os tempos medidos refletem a
orquestração no n8n e as APIs públicas, sem o tempo de inferência do modelo.
"""
from __future__ import annotations

import json
import statistics
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.test.yml"]
BASE = "http://localhost:5678/webhook/"
SAMPLES = ROOT / "samples"


def sh(args: list[str]) -> None:
    subprocess.run(args, cwd=ROOT, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


def post(path: str, body: dict) -> tuple[dict, float]:
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read() or b"{}")
    return data, time.perf_counter() - t0


def sample(name: str) -> dict:
    return json.loads((SAMPLES / f"{name}.json").read_text(encoding="utf-8"))


CASES = [
    # (fluxo, webhook, amostra, verificação, descrição)
    ("email", "email-intelligence", "email_reclamacao",
     lambda d: d["fila"] == "urgente" and d["rascunho_resposta"], "reclamação com prazo -> urgente, com rascunho"),
    ("email", "email-intelligence", "email_spam",
     lambda d: d["fila"] == "arquivar" and d["rascunho_resposta"] is None, "spam -> arquivar, sem rascunho"),
    ("email", "email-intelligence", "email_cobranca",
     lambda d: d["fila"] == "revisao_humana" and d["revisao_humana"], "cobrança com valor -> revisão humana"),
    ("email", "email-intelligence", "email_ambiguo",
     lambda d: d["fila"] == "revisao_humana", "confiança baixa -> revisão humana"),
    ("email", "email-intelligence", "email_falha_llm",
     lambda d: d["fila"] == "revisao_humana" and d["revisao_humana"] and "JSON inválido" in d["motivo"],
     "resposta inválida do LLM -> revisão humana, sem quebrar"),
    ("documento", "document-processing", "doc_nota",
     lambda d: d["tipo"] == "nota_fiscal" and d["pasta"] == "financeiro/notas" and not d["problemas"],
     "nota fiscal válida -> pasta do financeiro"),
    ("documento", "document-processing", "doc_contrato",
     lambda d: d["pasta"] == "juridico/contratos" and len(d["pontos_de_atencao"]) == 2,
     "contrato -> jurídico, com pontos de atenção"),
    ("documento", "document-processing", "doc_invalido",
     lambda d: d["pasta"] == "revisao_humana" and set(d["problemas"]) == {"cnpj_formato_invalido", "valor_total_ausente"},
     "CNPJ inválido e sem total -> revisão humana"),
    ("reuniao", "meeting-intelligence", "reuniao",
     lambda d: d["tarefas_sem_responsavel"] == 1 and "a definir" in d["ata_markdown"],
     "tarefa atribuída a quem não estava na reunião -> 'a definir'"),
    ("pesquisa", "research", "pesquisa",
     lambda d: d["citacoes_invalidas"] == 1 and len(d["fontes"]) == 2 and "wikipedia.org" in d["fontes"][0]["url"],
     "busca real na Wikipedia; citação inexistente removida"),
    ("relatorio", "data-report", None,
     lambda d: d["status"] == "ok" and d["numeros_sem_respaldo"] == [] and d["indicadores"]["observacoes"] >= 8,
     "dados reais do BCB; todos os números do texto conferem"),
]


def main() -> int:
    keep = "--manter" in sys.argv
    print("Subindo n8n + mock do LLM…")
    sh(COMPOSE + ["up", "-d", "--force-recreate"])
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen("http://localhost:5678/healthz", timeout=3)
                break
            except OSError:
                time.sleep(3)
        time.sleep(4)  # registro dos webhooks após o healthz
        results, failures = [], 0
        for flow, hook, name, check, desc in CASES:
            try:
                data, secs = post(hook, sample(name) if name else {})
                ok = bool(check(data))
            except Exception as e:  # falha de rede, KeyError na verificação etc.
                data, secs, ok = {"erro": str(e)}, 0.0, False
            failures += not ok
            results.append({"fluxo": flow, "caso": desc, "ok": ok, "segundos": round(secs, 2)})
            print(f"  {'✓' if ok else '✗'} [{flow}] {desc} ({secs:.2f}s)")
            if not ok:
                print("    resposta:", json.dumps(data, ensure_ascii=False)[:400])
        by_flow: dict[str, list[float]] = {}
        for r in results:
            by_flow.setdefault(r["fluxo"], []).append(r["segundos"])
        summary = {"data": datetime.now().isoformat(timespec="seconds"), "n8n": "2.47.7", "llm": "mock",
                   "casos": len(results), "aprovados": len(results) - failures,
                   "mediana_s_por_fluxo": {k: round(statistics.median(v), 2) for k, v in by_flow.items()},
                   "resultados": results}
        out = ROOT / "tests" / "resultados_e2e.json"
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n{len(results) - failures}/{len(results)} casos aprovados · detalhes em {out.relative_to(ROOT)}")
        return 1 if failures else 0
    finally:
        if not keep:
            sh(COMPOSE + ["down"])


if __name__ == "__main__":
    raise SystemExit(main())
