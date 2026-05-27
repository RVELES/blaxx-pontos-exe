"""
Blaxx Pontos — entrypoint do app Windows (PyWebView + WebView2).

Arquitetura:
  - DEFAULT: aponta para o backend de produção (Fly.io), banco Neon Postgres
    compartilhado com Web/Mac/iOS. O renderer é carregado LOCALMENTE via
    file:// e chama a API remota.
  - --local: sobe Flask embarcado em 127.0.0.1:5050 com SQLite local. Banco
    isolado, só para dev/offline.
  - --backend URL: aponta para outra instância remota (staging, branch).

Login: somente email/senha (Google Sign-In removido nesta versao).

Uso:
    python main.py                                # produção (default)
    python main.py --local                        # dev local
    python main.py --backend https://staging...   # outra instância
    python main.py --dev                          # + DevTools (F12)
    python main.py --no-tray                      # sem tray icon
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Optional

import webview  # pywebview >= 5.0

from config import APP_NAME, APP_VERSION, CONFIG, PRODUCTION_BACKEND_URL
from logging_setup import init_logging
import backend_runner
from backend_proxy import PROXY as _PROXY

log = logging.getLogger("blaxx.main")

_main_window: Optional["webview.Window"] = None
_tray: Optional[object] = None
_monitor: Optional[backend_runner.HealthMonitor] = None
_backend_url: str = CONFIG.backend.remote_url
_is_local_mode: bool = False


class BlaxxBridge:
    """API exposta ao JavaScript como `window.pywebview.api`."""

    def __init__(self, backend_url: str, is_local: bool):
        self._backend_url = backend_url
        self._is_local = is_local

    def backend_url(self) -> str:
        return self._backend_url

    def is_local(self) -> bool:
        return self._is_local

    def platform(self) -> str:
        return "win32"

    def versions(self) -> dict:
        return {
            "python": sys.version.split()[0],
            "pywebview": getattr(webview, "__version__", "unknown"),
            "app": APP_VERSION,
        }

    def notify(self, title: str, message: str) -> bool:
        if _tray is not None:
            try:
                _tray.notify(title, message)
                return True
            except Exception:
                log.exception("notify falhou")
        return False


def inject_blaxx_globals(window, backend_url: str, is_local: bool) -> None:
    """Injeta window.blaxx + persiste URL em localStorage."""
    py_version = sys.version.split()[0]
    js = (
        "(function() {"
        f"window.blaxx = {{"
        f"backendUrl: {backend_url!r},"
        f"isLocal: {str(is_local).lower()},"
        f"platform: 'win32',"
        f"versions: {{ python: {py_version!r}, app: {APP_VERSION!r} }}"
        f"}};"
        f"try {{ localStorage.setItem('blaxx_api_url', {backend_url!r}); }} catch (_) {{}}"
        "})();"
    )
    try:
        window.evaluate_js(js)
    except Exception:
        log.exception("inject_blaxx_globals falhou")


def resolve_initial_url(backend_url: str, is_local: bool) -> str:
    """Sempre carrega o renderer LOCAL via file://."""
    index_path = CONFIG.renderer_dir / "index.html"
    if not index_path.exists():
        raise FileNotFoundError(
            f"renderer/index.html nao encontrado em {CONFIG.renderer_dir}"
        )
    return index_path.as_uri()


def create_main_window(backend_url: str, is_local: bool) -> "webview.Window":
    initial_url = resolve_initial_url(backend_url, is_local)
    log.info("abrindo janela em %s", initial_url)

    bridge = BlaxxBridge(backend_url, is_local)
    window = webview.create_window(
        title=CONFIG.window.title,
        url=initial_url,
        js_api=bridge,
        width=CONFIG.window.width,
        height=CONFIG.window.height,
        min_size=(CONFIG.window.min_width, CONFIG.window.min_height),
        background_color=CONFIG.window.background_color,
        text_select=True,
    )

    def _on_loaded():
        inject_blaxx_globals(window, backend_url, is_local)

    window.events.loaded += _on_loaded
    return window


def show_main_window() -> None:
    if _main_window is None:
        return
    try:
        _main_window.show()
        _main_window.restore()
    except Exception:
        log.exception("show_main_window falhou")


def quit_app() -> None:
    log.info("quit_app: encerrando")
    if _monitor is not None:
        _monitor.stop()
    try:
        _PROXY.stop()
    except Exception:
        pass
    if _tray is not None:
        try:
            _tray.stop()
        except Exception:
            pass
    if _main_window is not None:
        try:
            _main_window.destroy()
        except Exception:
            pass


def start_tray() -> Optional[object]:
    try:
        from tray import BlaxxTray, is_available
    except Exception:
        log.exception("import do tray falhou")
        return None
    if not is_available():
        log.warning("tray indisponivel - seguindo sem ele")
        return None
    tray = BlaxxTray(on_open=show_main_window, on_quit=quit_app)
    tray.run_detached()
    tray.set_status("Iniciando...")
    return tray


def start_local_health_monitor() -> backend_runner.HealthMonitor:
    def _on_down(failures: int) -> None:
        if _tray is not None:
            _tray.set_status(f"Backend local falhou ({failures}x)")

    def _on_recovered() -> None:
        if _tray is not None:
            _tray.set_status("Online (local)")
            _tray.notify(APP_NAME, "Backend local reconectado.")

    def _on_restart_attempt() -> None:
        if _tray is not None:
            _tray.set_status("Reiniciando backend local...")

    monitor = backend_runner.HealthMonitor(
        on_down=_on_down,
        on_recovered=_on_recovered,
        on_restart_attempt=_on_restart_attempt,
    )
    monitor.start()
    return monitor


def start_remote_health_monitor(remote_url: str) -> backend_runner.HealthMonitor:
    def _on_down(failures: int) -> None:
        if _tray is not None:
            _tray.set_status(f"Sem conexao ({failures}x)")
            if failures == CONFIG.backend.health_failure_threshold:
                _tray.notify(APP_NAME,
                             "Backend remoto fora do ar. Verifique sua internet.")

    def _on_recovered() -> None:
        if _tray is not None:
            _tray.set_status("Online (remoto)")
            _tray.notify(APP_NAME, "Backend remoto recuperou.")

    monitor = backend_runner.HealthMonitor(
        on_down=_on_down,
        on_recovered=_on_recovered,
        check_fn=backend_runner.check_remote_health,
    )
    monitor._attempt_restart = lambda: None
    monitor.start()
    return monitor


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="blaxx-pontos", description=__doc__)
    p.add_argument("--local", action="store_true",
                   help="modo dev: sobe Flask embarcado com SQLite local (banco isolado)")
    p.add_argument("--backend", metavar="URL", default=None,
                   help="aponta para outra instancia remota (default: producao)")
    p.add_argument("--dev", action="store_true", help="abre DevTools (F12)")
    p.add_argument("--no-tray", action="store_true", help="desliga o tray icon")
    p.add_argument("--no-monitor", action="store_true", help="desliga o health monitor")
    p.add_argument("--no-proxy", action="store_true",
                   help="desliga o proxy local (renderer chama o backend remoto direto)")
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    init_logging()
    log.info("Blaxx Pontos %s - Windows app", APP_VERSION)
    log.info("CLI: local=%s backend=%s dev=%s no_tray=%s no_monitor=%s",
             args.local, args.backend, args.dev, args.no_tray, args.no_monitor)

    global _backend_url, _is_local_mode, _tray, _monitor, _main_window

    _is_local_mode = bool(args.local)

    if not args.no_tray:
        _tray = start_tray()

    if _is_local_mode:
        _backend_url = CONFIG.backend.local_url
        log.info("MODO LOCAL - Flask embarcado + SQLite em %s", CONFIG.db_url)
        if _tray is not None:
            _tray.set_status("Subindo backend local...")

        backend_runner.start_backend()
        if backend_runner.wait_for_backend():
            backend_runner.seed_if_empty()
            if _tray is not None:
                _tray.set_status("Online (local)")
        else:
            log.error("backend local nao respondeu - abrindo janela mesmo assim")
            if _tray is not None:
                _tray.set_status("Backend local indisponivel")

        if not args.no_monitor:
            _monitor = start_local_health_monitor()

    else:
        if args.backend:
            os.environ["BLAXX_BACKEND_URL"] = args.backend.rstrip("/")
            import importlib
            import config as _cfg
            importlib.reload(_cfg)
            globals()["CONFIG"] = _cfg.CONFIG
            upstream_url = _cfg.CONFIG.backend.remote_url
        else:
            upstream_url = CONFIG.backend.remote_url

        log.info("MODO REMOTO - backend compartilhado em %s", upstream_url)

        if args.no_proxy:
            _backend_url = upstream_url
            log.info("--no-proxy: renderer chamara o backend remoto direto")
        else:
            _backend_url = _PROXY.start(upstream_url)
            log.info("proxy local rodando em %s (upstream=%s)",
                     _backend_url, upstream_url)

        if _tray is not None:
            _tray.set_status(f"Conectando a {upstream_url}...")

        if backend_runner.wait_for_remote():
            log.info("backend remoto OK")
            if _tray is not None:
                _tray.set_status("Online (remoto)")
        else:
            log.warning("backend remoto nao respondeu - abrindo janela mesmo assim")
            if _tray is not None:
                _tray.set_status("Sem conexao com backend remoto")
                _tray.notify(APP_NAME,
                             "Nao foi possivel conectar ao backend. Verifique sua internet.")

        if not args.no_monitor:
            _monitor = start_remote_health_monitor(upstream_url)

    try:
        _main_window = create_main_window(_backend_url, _is_local_mode)
    except Exception:
        log.exception("criacao da janela falhou")
        return 2

    try:
        webview.start(debug=args.dev, gui="edgechromium")
    except Exception:
        log.exception("webview.start falhou")
        return 3

    log.info("janela fechada - desligando")
    quit_app()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
