"""Os mesmos casos do e2e.py, mas com o GEMINI REAL no lugar do servidor falso.

  GEMINI_API_KEY=... GEMINI_MODEL=gemini-3.5-flash-lite python tests/e2e_gemini.py

Diferente do e2e.py, aqui o resultado depende do modelo: um ✗ pode ser erro de classificação do Gemini, não bug do
fluxo. Por isso a saída completa de cada caso é salva em tests/resultados_gemini.json para leitura humana.
Fica de fora o caso "resposta inválida do LLM", que só existe no servidor falso. Cada caso faz 1 chamada ao modelo
(mais as retentativas do n8n em caso de erro 5xx/429).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e2e  # noqa: E402

ROOT = e2e.ROOT
RESULTS = ROOT / "tests" / "resultados_gemini.json"

# Alguns critérios do e2e.py medem se a REGRA EM CÓDIGO dispara diante de uma saída ruim roteirizada no servidor falso
# (ex.: o falso atribui uma tarefa a quem não estava na reunião; o falso inventa a citação [3]). Com o modelo real,
# se ele não erra, o critério reprova por não ter o que corrigir. Estas invariantes medem o que importa ao usuário e
# valem para qualquer modelo; são reportadas AO LADO do critério original, nunca no lugar dele.
def invariante(amostra: str, saida: dict) -> bool | None:
    if amostra == "reuniao":
        participantes = set(e2e.sample("reuniao")["participantes"]) | {"a definir"}
        return all(t["responsavel"] in participantes for t in saida["tarefas"])
    if amostra == "pesquisa":
        ids = {f["id"] for f in saida["fontes"]}
        citados = {int(n) for n in re.findall(r"\[(\d+)\]", saida["relatorio_markdown"])}
        return citados <= ids
    return None


def rescore() -> None:
    """Reaplica as invariantes à saída já salva, sem chamar o modelo."""
    d = json.loads(RESULTS.read_text(encoding="utf-8"))
    for r in d["resultados"]:
        r["invariante_ok"] = invariante(r["amostra"], r["saida"]) if "erro" not in r["saida"] else None
    RESULTS.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    for r in d["resultados"]:
        if r["invariante_ok"] is not None:
            print(f"  invariante [{r['fluxo']}] {'✓' if r['invariante_ok'] else '✗'} (critério do e2e: {'✓' if r['ok'] else '✗'})")
COMPOSE = ["docker", "compose", "-f", "docker-compose.yml"]  # sem o override do mock


def main() -> int:
    if "--rescore" in sys.argv:
        rescore()
        return 0
    if not os.environ.get("GEMINI_API_KEY"):
        raise SystemExit("defina GEMINI_API_KEY")
    model = os.environ.setdefault("GEMINI_MODEL", "gemini-3.5-flash-lite")
    print(f"Subindo n8n com o Gemini real ({model})…")
    subprocess.run(COMPOSE + ["up", "-d", "--force-recreate"], cwd=ROOT, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen("http://localhost:5678/healthz", timeout=3)
                break
            except OSError:
                time.sleep(3)
        time.sleep(4)
        results, ok_n = [], 0
        for flow, hook, name, check, desc in e2e.CASES:
            if name == "email_falha_llm":
                continue
            try:
                data, secs = e2e.post(hook, e2e.sample(name) if name else {})
                ok = bool(check(data))
            except Exception as e:
                data, secs, ok = {"erro": str(e)}, 0.0, False
            ok_n += ok
            results.append({"fluxo": flow, "caso": desc, "amostra": name, "ok": ok, "segundos": round(secs, 2),
                            "invariante_ok": invariante(name, data) if ok is not None and "erro" not in data else None, "saida": data})
            print(f"  {'✓' if ok else '✗'} [{flow}] {desc} ({secs:.1f}s)")
            if not ok:
                print("    saída:", json.dumps(data, ensure_ascii=False)[:300])
        out = RESULTS
        out.write_text(json.dumps({"data": datetime.now().isoformat(timespec="seconds"), "n8n": "2.47.7", "llm": model,
                                   "casos": len(results), "aprovados": ok_n, "resultados": results},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n{ok_n}/{len(results)} casos aprovados com o Gemini real ({model})")
    finally:
        subprocess.run(COMPOSE + ["down"], cwd=ROOT, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
