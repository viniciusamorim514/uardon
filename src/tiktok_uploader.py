from __future__ import annotations

import argparse
import json
import sys
import time
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TIKTOK_PROFILE = ROOT / ".tiktok-profile"
CDP_PORT = 9222


def log(msg: str) -> None:
    print(msg, flush=True)


# ---------- CDP helpers ----------

def _get_requests():
    try:
        import requests
        return requests
    except ImportError:
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "requests", "--quiet"])
        import requests
        return requests


def _get_ws():
    try:
        import websocket
        return websocket
    except ImportError:
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "websocket-client", "--quiet"])
        import websocket
        return websocket


def chrome_tabs():
    requests = _get_requests()
    try:
        r = requests.get(f"http://127.0.0.1:{CDP_PORT}/json", timeout=3)
        return r.json()
    except Exception as exc:
        raise RuntimeError(f"Chrome debug nao encontrado na porta {CDP_PORT}. Execute abrir_chrome_debug.bat primeiro.") from exc


def cdp_send(ws_obj, method, params=None, msg_id=1):
    websocket = _get_ws()
    payload = json.dumps({"id": msg_id, "method": method, "params": params or {}})
    ws_obj.send(payload)
    # Aguarda resposta com o id correto
    for _ in range(30):
        raw = ws_obj.recv()
        data = json.loads(raw)
        if data.get("id") == msg_id:
            return data
    return {}


def open_upload_tab():
    """Abre ou encontra a aba do TikTok Studio e retorna o websocket URL."""
    requests = _get_requests()
    tabs = chrome_tabs()
    # Procura aba do TikTok Studio
    for tab in tabs:
        if "tiktok" in tab.get("url", "").lower() and tab.get("type") == "page":
            return tab["webSocketDebuggerUrl"]
    # Abre nova aba
    try:
        r = requests.get(f"http://127.0.0.1:{CDP_PORT}/json/new?https://www.tiktok.com/tiktokstudio/upload", timeout=5)
        tab = r.json()
        return tab["webSocketDebuggerUrl"]
    except Exception:
        # Fallback: pega qualquer aba
        for tab in tabs:
            if tab.get("type") == "page":
                return tab["webSocketDebuggerUrl"]
    raise RuntimeError("Nenhuma aba disponivel no Chrome.")


def navigate_and_wait(ws_obj, url, wait=4):
    cdp_send(ws_obj, "Page.navigate", {"url": url}, msg_id=10)
    time.sleep(wait)


def find_file_input_node(ws_obj):
    """Retorna o nodeId do input[type=file]."""
    doc = cdp_send(ws_obj, "DOM.getDocument", {"depth": 0}, msg_id=20)
    root_id = doc.get("result", {}).get("root", {}).get("nodeId", 1)
    result = cdp_send(ws_obj, "DOM.querySelector", {"nodeId": root_id, "selector": 'input[type="file"]'}, msg_id=21)
    return result.get("result", {}).get("nodeId")


def set_file_input(ws_obj, node_id, file_path):
    cdp_send(ws_obj, "DOM.setFileInputFiles", {"nodeId": node_id, "files": [str(file_path)]}, msg_id=30)


def fill_caption_js(ws_obj, text):
    """Tenta preencher a legenda via JS."""
    escaped = text.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")
    script = f"""
(function() {{
    const selectors = [
        '[class*="caption"] [contenteditable]',
        '[data-testid*="caption"] [contenteditable]',
        '.public-DraftEditor-content',
        '[contenteditable="true"]',
        'textarea[name="caption"]',
        'textarea'
    ];
    for (const sel of selectors) {{
        const els = document.querySelectorAll(sel);
        for (const el of els) {{
            if (el.offsetParent !== null) {{
                el.focus();
                document.execCommand('selectAll', false, null);
                document.execCommand('insertText', false, `{escaped}`);
                return 'ok:' + sel;
            }}
        }}
    }}
    return 'not_found';
}})()
"""
    result = cdp_send(ws_obj, "Runtime.evaluate", {"expression": script, "returnByValue": True}, msg_id=40)
    return result.get("result", {}).get("result", {}).get("value", "")


# ---------- Main functions ----------

def upload(
    video_path: str,
    title: str,
    body: str,
    tags: list[str],
    auto_publish: bool = False,
) -> None:
    websocket = _get_ws()

    caption_parts = [p for p in [title, body, " ".join(tags)] if p.strip()]
    caption = "\n\n".join(caption_parts)

    log("Verificando Chrome com debug...")
    ws_url = open_upload_tab()
    log(f"Conectado: {ws_url[:60]}...")

    ws = websocket.create_connection(ws_url, timeout=10)
    try:
        log("Navegando para TikTok Studio upload...")
        navigate_and_wait(ws, "https://www.tiktok.com/tiktokstudio/upload", wait=5)

        log("Procurando input de arquivo...")
        node_id = None
        for attempt in range(10):
            node_id = find_file_input_node(ws)
            if node_id:
                break
            time.sleep(1.5)

        if not node_id:
            log("ERRO: Input de arquivo nao encontrado. TikTok pode estar pedindo login.")
            return

        log(f"Enviando arquivo: {video_path}")
        set_file_input(ws, node_id, video_path)
        log("Arquivo enviado. Aguardando processamento...")
        time.sleep(8)

        log("Preenchendo legenda...")
        result = fill_caption_js(ws, caption)
        if result.startswith("ok:"):
            log(f"Legenda preenchida via {result[3:]}")
        else:
            log("AVISO: Legenda nao preenchida automaticamente — cole manualmente.")

        log("PRONTO: Revise no TikTok Studio e clique Publicar.")

    finally:
        try:
            ws.close()
        except Exception:
            pass


def setup_login() -> None:
    """Instrucoes para configurar o Chrome com debug."""
    log("Para usar o upload automatico:")
    log("1. Execute 'abrir_chrome_debug.bat' na pasta do projeto")
    log("2. Faca login no TikTok no Chrome que abrir")
    log("3. Mantenha o Chrome aberto")
    log("4. Use o botao TikTok no Studio para fazer upload automatico")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upload automatico para o TikTok Studio.")
    parser.add_argument("--setup", action="store_true", help="Mostrar instrucoes de configuracao")
    parser.add_argument("--video", default="", help="Caminho do .mp4")
    parser.add_argument("--title", default="")
    parser.add_argument("--body", default="")
    parser.add_argument("--tags", default="")
    parser.add_argument("--auto-publish", action="store_true")
    args = parser.parse_args()

    if args.setup:
        setup_login()
    else:
        if not args.video:
            log("ERRO: --video obrigatorio")
            sys.exit(1)
        tags = [t for t in args.tags.split() if t.startswith("#")]
        upload(args.video, args.title, args.body, tags, auto_publish=args.auto_publish)
