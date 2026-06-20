"""
Google Sign-In nativo no Windows · Authorization Code Flow + PKCE.

Refatorado pra suportar DOIS modos de apresentação do consent screen:

    1. EMBEDDED (default no app): a janela do Google abre dentro do próprio
       app como uma child PyWebView window. UX coesa, sem trocar de contexto
       pro navegador padrão, sem dependência de browser default funcional.
    2. EXTERNAL (compat / fallback): abre no navegador padrão via
       webbrowser.open(). Necessário se o Google bloquear o WebView2
       embarcado por user-agent.

Em ambos os modos a captura do callback usa o mesmo padrão: loopback HTTP
server em 127.0.0.1:<porta livre> (RFC 8252, "OAuth 2.0 for Native Apps").

Fluxo (passos abstratos):
    1. Gera code_verifier + code_challenge (PKCE S256), state, nonce.
    2. Sobe loopback HTTP server numa porta efêmera.
    3. Constrói auth_url do Google com redirect_uri=http://127.0.0.1:porta/callback.
    4. Apresenta a auth_url ao usuário (embedded ou external).
    5. Aguarda o callback no /callback?code=...&state=...
    6. Valida state, troca code+verifier por id_token via POST /token.
    7. Retorna {id_token, nonce} pro backend Blaxx (/auth/google) validar.

PKCE substitui o client_secret: em apps desktop não há jeito seguro de
guardar secret. O code_verifier prova posse do request original.

API de alto nível:
    - GoogleAuthFlow(client_id, client_secret=None): inicia (sobe server,
      monta auth_url). Não bloqueia.
    - flow.wait_for_callback(timeout): bloqueia esperando o /callback.
    - flow.complete(): valida e troca o code, retorna id_token+nonce.
    - flow.cancel(): libera porta e sinaliza cancelamento.
    - flow.close(): cleanup obrigatório (use try/finally).

API legada:
    - sign_in(client_id, ...): wrapper síncrono que abre o navegador
      padrão e espera o callback. Mantido pra compat.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import logging
import secrets
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from typing import Optional, TypedDict

log = logging.getLogger("blaxx.google_auth")

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


class GoogleAuthError(Exception):
    """Erro genérico do fluxo Google Sign-In."""


class SignInResult(TypedDict):
    id_token: str
    nonce: str


# ---------------------------------------------------------------------------
# PKCE helpers (RFC 7636)
# ---------------------------------------------------------------------------
def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _pkce_pair() -> tuple[str, str]:
    """Retorna (code_verifier, code_challenge) prontos pro fluxo S256."""
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _free_port() -> int:
    """Pede ao SO uma porta livre em 127.0.0.1."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# Página HTML mostrada apos o callback (renderizada DENTRO da child window)
# ---------------------------------------------------------------------------
_SUCCESS_HTML = ("""<!doctype html>
<html lang="pt-BR"><head>
<meta charset="utf-8">
<title>BlaXx · Login conclu&iacute;do</title>
<style>
  html,body{margin:0;height:100%;background:#0A0A0A;color:#fff;
            font-family:-apple-system,Segoe UI,Inter,system-ui,sans-serif;
            display:flex;align-items:center;justify-content:center;
            text-align:center;padding:24px}
  .card{max-width:420px}
  .logo{font-size:36px;font-weight:700;letter-spacing:-0.02em}
  .lime{color:#7CFF00}
  .tag{margin-top:6px;font-size:11px;letter-spacing:.18em;text-transform:uppercase;
       color:rgba(255,255,255,.45)}
  h2{margin-top:36px;font-size:22px;font-weight:600}
  p{color:rgba(255,255,255,.7);font-size:14px;margin:8px 0 0 0;line-height:1.5}
  .spinner{margin:28px auto 0;width:18px;height:18px;border-radius:50%;
           border:2px solid rgba(255,255,255,.15);border-top-color:#7CFF00;
           animation:spin 0.8s linear infinite}
  @keyframes spin{to{transform:rotate(360deg)}}
</style>
</head><body>
<div class="card">
  <div class="logo">Bla<span class="lime">Xx</span></div>
  <div class="tag">Plataforma institucional de pontos</div>
  <h2>Login conclu&iacute;do</h2>
  <p>Voltando ao aplicativo&hellip;</p>
  <div class="spinner"></div>
</div>
</body></html>
""").encode("utf-8")

_ERROR_HTML = ("""<!doctype html>
<html lang="pt-BR"><head>
<meta charset="utf-8">
<title>BlaXx · Erro</title>
<style>
  html,body{margin:0;height:100%;background:#0A0A0A;color:#fff;
            font-family:-apple-system,Segoe UI,Inter,system-ui,sans-serif;
            display:flex;align-items:center;justify-content:center;
            text-align:center;padding:24px}
  h2{color:#fca5a5;margin:0 0 12px 0}
  p{color:rgba(255,255,255,.7);font-size:14px;margin:0}
</style></head><body><div>
  <h2>Falha ao autenticar com Google</h2>
  <p>Volte ao aplicativo e tente novamente.</p>
</div></body></html>
""").encode("utf-8")


# ---------------------------------------------------------------------------
# Loopback HTTP handler · captura ?code=
# ---------------------------------------------------------------------------
class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Captura GET /callback do Google e armazena no result_holder."""

    def log_message(self, *args, **kwargs) -> None:  # noqa: D401, ARG002
        pass  # suprime logs barulhentos do BaseHTTPRequestHandler

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if not parsed.path.startswith("/callback"):
            self.send_response(404)
            self.end_headers()
            return

        params = urllib.parse.parse_qs(parsed.query)
        result = self.server.result_holder  # type: ignore[attr-defined]
        result["code"] = (params.get("code") or [None])[0]
        result["state"] = (params.get("state") or [None])[0]
        result["error"] = (params.get("error") or [None])[0]
        result["error_description"] = (params.get("error_description") or [None])[0]
        self.server.done_event.set()  # type: ignore[attr-defined]

        body = _SUCCESS_HTML if result["code"] else _ERROR_HTML
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass


class _LoopbackServer(http.server.HTTPServer):
    """HTTPServer com slots extras pra comunicar com a thread principal."""

    def __init__(self, addr, handler):
        super().__init__(addr, handler)
        self.result_holder: dict = {
            "code": None,
            "state": None,
            "error": None,
            "error_description": None,
        }
        self.done_event = threading.Event()


# ---------------------------------------------------------------------------
# Token exchange (RFC 6749 + PKCE)
# ---------------------------------------------------------------------------
def _exchange_code(
    client_id: str,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    client_secret: Optional[str] = None,
    timeout: float = 15.0,
) -> str:
    """POST https://oauth2.googleapis.com/token · retorna id_token."""
    payload = {
        "code": code,
        "client_id": client_id,
        "code_verifier": code_verifier,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }
    if client_secret:
        payload["client_secret"] = client_secret

    body = urllib.parse.urlencode(payload).encode("ascii")
    req = urllib.request.Request(
        GOOGLE_TOKEN_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8")
        except Exception:
            err_body = str(e)
        raise GoogleAuthError(
            f"Google /token retornou HTTP {e.code}: {err_body[:300]}"
        )
    except urllib.error.URLError as e:
        raise GoogleAuthError(f"erro de rede ao trocar code: {e}")

    id_token = data.get("id_token")
    if not id_token:
        raise GoogleAuthError(f"Google /token sem id_token na resposta: {data}")
    return id_token


def _build_auth_url(client_id: str, redirect_uri: str, challenge: str,
                    state: str, nonce: str) -> str:
    return GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "nonce": nonce,
        "prompt": "select_account",
        "access_type": "online",
    })


# ---------------------------------------------------------------------------
# API de alto nível · GoogleAuthFlow (modo embedded)
# ---------------------------------------------------------------------------
class GoogleAuthFlow:
    """Estado vivo de um fluxo OAuth · seguro pra usar com child PyWebView.

    Uso:
        flow = GoogleAuthFlow(client_id)
        try:
            # 1. abra flow.auth_url onde quiser (child window, browser, ...)
            # 2. espere o callback
            if not flow.wait_for_callback(300):
                raise TimeoutError
            result = flow.complete()  # {id_token, nonce}
        finally:
            flow.close()
    """

    def __init__(self, client_id: str, client_secret: Optional[str] = None):
        if not client_id:
            raise GoogleAuthError("BLAXX_GOOGLE_CLIENT_ID nao configurado")

        self.client_id = client_id
        self.client_secret = client_secret
        self.verifier, challenge = _pkce_pair()
        self.state = secrets.token_urlsafe(16)
        self.nonce = secrets.token_urlsafe(24)
        self.port = _free_port()
        self.redirect_uri = f"http://127.0.0.1:{self.port}/callback"
        self.auth_url = _build_auth_url(
            client_id=client_id,
            redirect_uri=self.redirect_uri,
            challenge=challenge,
            state=self.state,
            nonce=self.nonce,
        )

        self._server = _LoopbackServer(("127.0.0.1", self.port), _CallbackHandler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name=f"google-oauth-cb-{self.port}",
            daemon=True,
        )
        self._thread.start()
        self._cancelled = False
        log.info("Google flow iniciado · client=%s... port=%d",
                 client_id[:14], self.port)

    @property
    def callback_received(self) -> bool:
        return self._server.done_event.is_set()

    def wait_for_callback(self, timeout: float = 300.0) -> bool:
        """Bloqueia ate o callback chegar OU cancel() ser chamado.

        Retorna True se chegou code/erro do Google, False se foi cancelado
        ou estourou timeout.
        """
        ok = self._server.done_event.wait(timeout=timeout)
        if self._cancelled:
            return False
        return ok

    def cancel(self) -> None:
        """Sinaliza cancelamento — wait_for_callback() desbloqueia."""
        self._cancelled = True
        self._server.done_event.set()
        log.info("Google flow cancelado pelo usuario (port=%d)", self.port)

    def complete(self) -> SignInResult:
        """Valida state e troca o code · retorna {id_token, nonce}."""
        if self._cancelled and not self._server.result_holder.get("code"):
            raise GoogleAuthError("login cancelado pelo usuario")
        result = self._server.result_holder
        if result.get("error"):
            desc = result.get("error_description") or ""
            raise GoogleAuthError(f"Google: {result['error']} {desc}".strip())
        if not result.get("code"):
            raise GoogleAuthError("Google nao retornou code de autorizacao")
        if result.get("state") != self.state:
            raise GoogleAuthError("state mismatch · possivel tampering, abortando")

        id_token = _exchange_code(
            client_id=self.client_id,
            code=result["code"],
            code_verifier=self.verifier,
            redirect_uri=self.redirect_uri,
            client_secret=self.client_secret,
        )
        log.info("Google sign-in OK · id_token len=%d", len(id_token))
        return {"id_token": id_token, "nonce": self.nonce}

    def close(self) -> None:
        """Libera porta e thread do loopback server. Idempotente."""
        try:
            self._server.shutdown()
        except Exception:
            pass
        try:
            self._server.server_close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# API legada · sign_in() sincrono via navegador padrao (fallback)
# ---------------------------------------------------------------------------
def sign_in(
    client_id: str,
    client_secret: Optional[str] = None,
    timeout_s: float = 300.0,
    open_browser: bool = True,
) -> SignInResult:
    """Versao sincrona — abre no NAVEGADOR PADRAO e bloqueia ate completar.

    Mantida por compatibilidade. O app Windows usa GoogleAuthFlow direto
    pra abrir em janela embedded; isto aqui e' fallback.
    """
    flow = GoogleAuthFlow(client_id, client_secret)
    try:
        if open_browser:
            opened = webbrowser.open(flow.auth_url, new=2, autoraise=True)
            if not opened:
                log.warning("webbrowser.open retornou False")
        else:
            log.info("auth_url=%s", flow.auth_url)

        if not flow.wait_for_callback(timeout=timeout_s):
            raise GoogleAuthError("timeout aguardando autorizacao do Google")
        return flow.complete()
    finally:
        flow.close()
