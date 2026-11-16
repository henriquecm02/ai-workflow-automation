"""Servidor que imita o endpoint generateContent do Gemini, para testar os fluxos sem chave e sem custo.

- Valida o formato da requisição (instrução de sistema, conteúdo, schema de saída JSON).
- Identifica a tarefa pela linha "Tarefa: <id>" da instrução e escolhe a resposta roteirizada em
  fixtures/<id>.json pelo primeiro trecho de `match` encontrado no texto do usuário.
- Confere se a resposta roteirizada tem os campos obrigatórios do schema (pega fixture desatualizada).
- Cenários de falha: "[[falha_llm]]" no texto devolve JSON inválido; "[[erro_api]]" devolve HTTP 500.
- `relatorio_indicador` é gerado a partir dos números recebidos (ecoa os valores reais da API do BCB).
"""
from __future__ import annotations

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
LOG = Path(os.getenv("MOCK_LOG", "/tmp/mock_llm_requests.jsonl"))


def br(v: float, casas: int = 2) -> str:
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def relatorio(user_text: str) -> dict:
    ind = json.loads(user_text.split("\n", 1)[1])
    casas = 4 if ind["ultimo"] < 100 else 2
    return {"titulo": "Dólar na semana",
            "resumo": f"O dólar PTAX fechou em R$ {br(ind['ultimo'], casas)} em {ind['ultima_data']}. "
                      f"Nos últimos 5 pregões a variação foi de {br(ind['var_5_pregoes_pct'])}%.",
            "destaques": [f"Mínimo do período: R$ {br(ind['minimo'], casas)}",
                          f"Máximo do período: R$ {br(ind['maximo'], casas)}",
                          f"Variação no período: {br(ind['var_periodo_pct'])}%"]}


def pick(task: str, user_text: str) -> dict:
    if task == "relatorio_indicador":
        return relatorio(user_text)
    options = json.loads((FIXTURES / f"{task}.json").read_text(encoding="utf-8"))
    for opt in options:
        if opt.get("match", "") in user_text:
            return opt["response"]
    raise KeyError(f"Nenhuma resposta roteirizada para a tarefa {task}")


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args) -> None:  # silencioso
        pass

    def do_GET(self) -> None:
        self._send(200, {"ok": True})

    def do_POST(self) -> None:
        if not re.match(r"^/v1beta/models/[\w.\-]+:generateContent$", self.path):
            return self._send(404, {"error": {"message": f"rota desconhecida {self.path}"}})
        if not self.headers.get("x-goog-api-key"):
            return self._send(401, {"error": {"message": "x-goog-api-key ausente"}})
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        system = " ".join(p.get("text", "") for p in req.get("systemInstruction", {}).get("parts", []))
        user = " ".join(p.get("text", "") for c in req.get("contents", []) for p in c.get("parts", []))
        cfg = req.get("generationConfig", {})
        problems = [m for ok, m in [(system, "systemInstruction vazio"), (user, "contents vazio"),
                                    (cfg.get("responseMimeType") == "application/json", "responseMimeType != json"),
                                    (isinstance(cfg.get("responseJsonSchema"), dict), "responseJsonSchema ausente")]
                    if not ok]
        if problems:
            return self._send(400, {"error": {"message": "; ".join(problems)}})
        task = (re.search(r"Tarefa: (\w+)", system) or [None, "?"])[1]
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"tarefa": task, "chars_entrada": len(user)}, ensure_ascii=False) + "\n")
        if "[[erro_api]]" in user:
            return self._send(500, {"error": {"code": 500, "message": "erro simulado"}})
        if "[[falha_llm]]" in user:
            text = "Desculpe, não consegui gerar o JSON."
        else:
            try:
                resp = pick(task, user)
            except (KeyError, FileNotFoundError, json.JSONDecodeError) as e:
                return self._send(500, {"error": {"message": str(e)}})
            missing = [k for k in cfg["responseJsonSchema"].get("required", []) if k not in resp]
            if missing:
                return self._send(500, {"error": {"message": f"fixture de {task} sem campos: {missing}"}})
            text = json.dumps(resp, ensure_ascii=False)
        self._send(200, {"candidates": [{"content": {"role": "model", "parts": [{"text": text}]},
                                         "finishReason": "STOP"}],
                         "usageMetadata": {"promptTokenCount": len(user) // 4, "candidatesTokenCount": len(text) // 4},
                         "modelVersion": "mock"})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    print(f"mock-llm ouvindo em :{port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
