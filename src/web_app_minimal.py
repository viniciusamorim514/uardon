"""Servidor web minimal do Uardon - versão simplificada para debug."""

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
HOST = "127.0.0.1"
PORT = 8787


class SimpleHandler(BaseHTTPRequestHandler):
    """Handler HTTP simples para debug."""

    def do_GET(self):
        """Servir arquivos estáticos."""
        if self.path == "/" or self.path == "/index.html":
            self.send_file(WEB / "index.html", "text/html")
        elif self.path == "/app.css":
            self.send_file(WEB / "app.css", "text/css")
        elif self.path == "/app.js":
            self.send_file(WEB / "app.js", "application/javascript")
        elif self.path == "/api/state":
            self.send_json({
                "stage": "Aguardando link",
                "progress": 0,
                "running": False
            })
        elif self.path == "/api/candidates":
            self.send_json({
                "candidates": []
            })
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")

    def do_POST(self):
        """Processar requisições POST."""
        if self.path == "/api/run":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                if content_length == 0:
                    self.send_json({"ok": False, "error": "Corpo vazio"}, 400)
                    return

                body_bytes = self.rfile.read(content_length)
                body = body_bytes.decode("utf-8")
                payload = json.loads(body)

                url = payload.get("url", "").strip()
                if not url:
                    self.send_json({"ok": False, "error": "URL vazia"}, 400)
                    return

                # Simular sucesso
                job_id = f"job-{int(time.time())}"
                result = {
                    "ok": True,
                    "job_id": job_id
                }
                self.send_json(result, 200)
                return
            except json.JSONDecodeError as e:
                print(f"[ERRO] JSON inválido: {e}", file=sys.stderr)
                self.send_json({"ok": False, "error": f"JSON inválido: {e}"}, 400)
            except Exception as e:
                print(f"[ERRO] /api/run: {e}", file=sys.stderr)
                self.send_json({"ok": False, "error": str(e)}, 500)
        else:
            self.send_response(404)
            self.end_headers()

    def send_file(self, path, content_type):
        """Enviar arquivo estático."""
        try:
            content = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", len(content))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(f"Erro: {e}".encode())

    def send_json(self, data, status=200):
        """Enviar resposta JSON."""
        content = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(content))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format, *args):
        """Suprimir logs padrão do servidor."""
        pass


def main():
    """Iniciar servidor."""
    server = ThreadingHTTPServer((HOST, PORT), SimpleHandler)
    print(f"[OK] Servidor rodando em http://{HOST}:{PORT}")
    print(f"     Arquivos servindo de: {WEB}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[ENCERRADO] Servidor parado")
        server.shutdown()


if __name__ == "__main__":
    main()
