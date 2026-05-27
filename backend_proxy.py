"""
Backend proxy — proxy HTTP local que repassa requests para o backend remoto.

Razão de existir: o renderer Windows é servido via `file://` (sem origem),
e o navegador embarcado envia `Origin: null` nos fetches. Se o backend remoto
não tem `CORS_ORIGINS=*` ou não aceita `null` explicitamente, ele rejeita
todas as chamadas com erro CORS.

Solução: subir um proxy local em `127.0.0.1:<porta-livre>` que recebe os
requests do renderer e repassa para o backend remoto (Fly.io / staging /
custom). Do ponto de vista do navegador, é tudo `same-origin` — o problema
de CORS some.

Princípios:
  - Thread daemon (encerra junto com o app)
  - Sem dependências externas (urllib + http.server da stdlib)
  - Idempotente: chamar start() duas vezes é no-op
  - Suporta GET/POST/PUT/PATCH/DELETE/OPTIONS e qualquer header
  - Repassa Authorization (JWT Bearer) intacto
  - Streaming: passa o corpo da resposta inteiro (suficiente pro Blaxx)
"""

from __future__ import annotations

import http.server
import logging
import socket
import socketserver
import ssl
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

log = logging.getLogger("blaxx.proxy")

# Headers que NUNCA devem ser repassados (controlados pela camada HTTP)
_HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host",
    "content-length",   # recalculado pela camada Python
})


def _free_port() -> int:
    """Pede ao SO uma porta livre em 127.0.0.1."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _ProxyHandler(http.server.BaseHTTPRequestHandler):
    # Suprime logs default (já temos o nosso)
    def log_message(self, *args, **kwargs):  # noqa: ARG002, D401
        pass

    @property
    def _upstream(self) -> str:
        return self.server.upstream_url  # type: ignore[attr-defined]

    def _proxy(self, method: str) -> None:
        path = self.path  # já vem com query string
        url = self._upstream.rstrip("/") + path

        # Lê corpo (se houver)
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length > 0 else None

        # Copia headers, filtrando hop-by-hop
        headers = {}
        for k, v in self.headers.items():
            if k.lower() in _HOP_BY_HOP:
                continue
            headers[k] = v
        # Força host correto para o upstream
        parsed = urllib.parse.urlparse(self._upstream)
        headers["Host"] = parsed.netloc

        log.debug("%s %s -> %s", method, path, url)

        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            ctx = ssl.create_default_context() if url.startswith("https://") else None
            with urllib.request.urlopen(req, timeout=30, context=ctx) as up:
                status = up.status
                resp_body = up.read()
                resp_headers = up.headers
        except urllib.error.HTTPError as e:
            # Erro HTTP do upstream — repassa com o status original
            status = e.code
            try:
                resp_body = e.read()
            except Exception:
                resp_body = b""
            resp_headers = e.headers if hasattr(e, "headers") else {}
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            log.warning("proxy upstream falhou: %s", e)
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            err_body = f'{{"error":"upstream unreachable","detail":"{e}"}}'.encode("utf-8")
            self.send_header("Content-Length", str(len(err_body)))
            self.end_headers()
            self.wfile.write(err_body)
            return

        # Envia resposta
        self.send_response(status)
        # Adiciona CORS aberto — o proxy só fala com 127.0.0.1 mesmo
        seen_acao = False
        for k, v in (resp_headers.items() if hasattr(resp_headers, "items") else []):
            if k.lower() in _HOP_BY_HOP:
                continue
            if k.lower() == "access-control-allow-origin":
                seen_acao = True
            self.send_header(k, v)
        if not seen_acao:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods",
                             "GET, POST, PUT, PATCH, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers",
                             "Content-Type, Authorization, X-Requested-With, X-Request-ID")
        self.send_header("Content-Length", str(len(resp_body)))
        self.end_headers()
        if resp_body:
            self.wfile.write(resp_body)

    # Métodos HTTP — todos delegam pro _proxy
    def do_GET(self):    self._proxy("GET")     # noqa: N802
    def do_POST(self):   self._proxy("POST")    # noqa: N802
    def do_PUT(self):    self._proxy("PUT")     # noqa: N802
    def do_PATCH(self):  self._proxy("PATCH")   # noqa: N802
    def do_DELETE(self): self._proxy("DELETE")  # noqa: N802
    def do_HEAD(self):   self._proxy("HEAD")    # noqa: N802
    def do_OPTIONS(self):  # noqa: N802
        # Preflight CORS — responde direto sem ir ao upstream
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods",
                         "GET, POST, PUT, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers",
                         "Content-Type, Authorization, X-Requested-With, X-Request-ID")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()


class _ThreadedProxyServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class BackendProxy:
    """Singleton-ish proxy local. Use `start(upstream_url)` para subir."""

    def __init__(self):
        self._server: Optional[_ThreadedProxyServer] = None
        self._thread: Optional[threading.Thread] = None
        self._port: Optional[int] = None
        self._lock = threading.Lock()

    @property
    def port(self) -> Optional[int]:
        return self._port

    @property
    def local_url(self) -> Optional[str]:
        return f"http://127.0.0.1:{self._port}" if self._port else None

    def start(self, upstream_url: str) -> str:
        """Sobe o proxy se ainda não estiver rodando. Retorna a URL local."""
        with self._lock:
            if self._server is not None:
                return self.local_url  # type: ignore[return-value]

            port = _free_port()
            server = _ThreadedProxyServer(("127.0.0.1", port), _ProxyHandler)
            server.upstream_url = upstream_url.rstrip("/")  # type: ignore[attr-defined]
            self._server = server
            self._port = port

            t = threading.Thread(target=server.serve_forever,
                                 name="backend-proxy", daemon=True)
            t.start()
            self._thread = t
            log.info("backend proxy: 127.0.0.1:%d -> %s", port, upstream_url)
            return self.local_url  # type: ignore[return-value]

    def stop(self) -> None:
        with self._lock:
            if self._server is not None:
                try:
                    self._server.shutdown()
                except Exception:
                    pass
                try:
                    self._server.server_close()
                except Exception:
                    pass
                self._server = None
            self._port = None


# Singleton — uso prático
PROXY = BackendProxy()
