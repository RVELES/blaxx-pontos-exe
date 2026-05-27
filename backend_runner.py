"""
Backend runner — sobe e supervisiona o Flask embarcado (modo --local) e
oferece verificações de saúde para o backend remoto (modo default).

Componentes:
  - start_backend()           sobe o Flask em thread daemon (modo local)
  - wait_for_backend()        espera /health local responder
  - check_health(url=None)    single-shot health check (local ou URL custom)
  - check_remote_health()     check do backend remoto (Fly.io / staging)
  - wait_for_remote()         espera o backend remoto responder
  - seed_if_empty()           roda seed.py se banco local vazio
  - HealthMonitor             thread que polla periodicamente e notifica
                              callbacks; com auto-restart no modo local
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Callable, Optional

from config import CONFIG

log = logging.getLogger("blaxx.backend")

_flask_app = None
_backend_thread: Optional[threading.Thread] = None
_backend_lock = threading.Lock()


def _ensure_env() -> None:
    """Garante variáveis de ambiente esperadas pelo Config do Flask."""
    os.environ.setdefault("BLAXX_BACKEND_HOST", CONFIG.backend.host)
    os.environ.setdefault("BLAXX_BACKEND_PORT", str(CONFIG.backend.port))
    os.environ.setdefault("DATABASE_URL", CONFIG.db_url)

    if "SECRET_KEY" not in os.environ:
        import secrets as _secrets
        os.environ["SECRET_KEY"] = _secrets.token_hex(32)
        os.environ.setdefault("JWT_SECRET_KEY", os.environ["SECRET_KEY"])

    os.environ.setdefault("RATELIMIT_STORAGE_URI", "memory://")
    backend_dir = str(CONFIG.backend_dir)
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)


def start_backend() -> threading.Thread:
    """Sobe o Flask embarcado em thread daemon. Idempotente."""
    global _flask_app, _backend_thread

    with _backend_lock:
        if _backend_thread and _backend_thread.is_alive():
            log.debug("backend já rodando — start_backend é no-op")
            return _backend_thread

        _ensure_env()

        from app import create_app  # type: ignore[import-not-found]

        _flask_app = create_app()

        def _run() -> None:
            log.info("Flask subindo em %s", CONFIG.backend.local_url)
            try:
                _flask_app.run(  # type: ignore[union-attr]
                    host=CONFIG.backend.host,
                    port=CONFIG.backend.port,
                    debug=False,
                    use_reloader=False,
                    threaded=True,
                )
            except OSError as e:
                if "Address already in use" in str(e) or "10048" in str(e):
                    log.error(
                        "Porta %d ocupada — defina BLAXX_BACKEND_PORT pra outra livre",
                        CONFIG.backend.port,
                    )
                else:
                    log.exception("Flask falhou")
            except Exception:
                log.exception("Flask encerrou com erro")

        _backend_thread = threading.Thread(target=_run, name="flask-backend", daemon=True)
        _backend_thread.start()
        return _backend_thread


def wait_for_backend(timeout_s: Optional[float] = None) -> bool:
    """Aguarda /health LOCAL responder. Retorna True quando OK; False se timeout."""
    timeout = timeout_s if timeout_s is not None else CONFIG.backend.health_timeout_s
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if check_health():
            log.info("/health local OK em %.2fs", time.monotonic() - start)
            return True
        time.sleep(0.3)
    log.error("timeout aguardando /health local (%.0fs)", timeout)
    return False


def check_health(url: Optional[str] = None, timeout: float = 1.5) -> bool:
    """Single shot: True se o backend responde em /health.

    Aceita URL explícita; sem parâmetro usa o backend LOCAL configurado.
    """
    target = url or CONFIG.backend.health_url
    try:
        with urllib.request.urlopen(target, timeout=timeout) as r:
            return 200 <= r.status < 400
    except (urllib.error.URLError, ConnectionError, OSError, TimeoutError):
        return False


def check_remote_health(timeout: Optional[float] = None) -> bool:
    """Checa /health do backend remoto (Fly.io / staging / custom)."""
    t = timeout if timeout is not None else CONFIG.backend.remote_health_timeout_s
    return check_health(CONFIG.backend.remote_health_url, timeout=t)


def wait_for_remote(timeout_s: Optional[float] = None) -> bool:
    """Aguarda o backend remoto responder /health (default: 8s)."""
    timeout = timeout_s if timeout_s is not None else CONFIG.backend.remote_health_timeout_s
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if check_remote_health():
            log.info("backend remoto OK em %.2fs", time.monotonic() - start)
            return True
        time.sleep(0.4)
    log.error("backend remoto não respondeu em %.0fs", timeout)
    return False


def seed_if_empty() -> None:
    """Roda backend/seed.py se a tabela users estiver vazia (modo local)."""
    try:
        _ensure_env()
        from app import create_app  # type: ignore[import-not-found]
        from app.extensions import db  # type: ignore[import-not-found]
        from app.models import User  # type: ignore[import-not-found]

        a = _flask_app or create_app()
        with a.app_context():
            user_count = db.session.query(User).count()
        if user_count > 0:
            log.debug("banco já tem %d usuários — pulando seed", user_count)
            return

        seed_path = CONFIG.backend_dir / "seed.py"
        if not seed_path.exists():
            log.warning("seed.py não encontrado em %s", seed_path)
            return

        log.info("banco vazio — rodando seed inicial…")
        import importlib.util as _ilu

        spec = _ilu.spec_from_file_location("blaxx_seed", str(seed_path))
        if spec is None or spec.loader is None:
            log.error("falha ao carregar seed.py")
            return
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        log.info("seed concluído")
    except Exception:
        log.exception("seed falhou (segue mesmo assim)")


class HealthMonitor(threading.Thread):
    """Thread que monitora /health periodicamente e dispara callbacks.

    Por padrão monitora o backend LOCAL e tenta auto-restart após N falhas.
    Para monitorar o remoto, sobrescreva `check_fn` ou monkey-patch
    `backend_runner.check_health`.
    """

    def __init__(
        self,
        on_down: Optional[Callable[[int], None]] = None,
        on_recovered: Optional[Callable[[], None]] = None,
        on_restart_attempt: Optional[Callable[[], None]] = None,
        check_fn: Optional[Callable[[], bool]] = None,
    ):
        super().__init__(name="health-monitor", daemon=True)
        self._stop_event = threading.Event()
        self._on_down = on_down
        self._on_recovered = on_recovered
        self._on_restart_attempt = on_restart_attempt
        self._check_fn = check_fn or check_health
        self._consecutive_failures = 0
        self._was_down = False

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        log.info("health monitor iniciado (intervalo=%ss, threshold=%d)",
                 CONFIG.backend.health_check_interval_s,
                 CONFIG.backend.health_failure_threshold)
        while not self._stop_event.is_set():
            ok = self._check_fn()
            if ok:
                if self._was_down:
                    log.info("backend recuperou")
                    self._was_down = False
                    self._consecutive_failures = 0
                    if self._on_recovered:
                        try:
                            self._on_recovered()
                        except Exception:
                            log.exception("on_recovered callback falhou")
            else:
                self._consecutive_failures += 1
                log.warning("/health falhou (#%d)", self._consecutive_failures)
                self._was_down = True
                if self._on_down:
                    try:
                        self._on_down(self._consecutive_failures)
                    except Exception:
                        log.exception("on_down callback falhou")

                if self._consecutive_failures >= CONFIG.backend.health_failure_threshold:
                    log.error("backend caído por %d checks consecutivos — tentando restart",
                              self._consecutive_failures)
                    if self._on_restart_attempt:
                        try:
                            self._on_restart_attempt()
                        except Exception:
                            log.exception("on_restart_attempt callback falhou")
                    self._attempt_restart()

            self._stop_event.wait(CONFIG.backend.health_check_interval_s)

    def _attempt_restart(self) -> None:
        """Reinicia o Flask (modo local). Override pra desabilitar."""
        global _backend_thread
        with _backend_lock:
            _backend_thread = None
        try:
            start_backend()
            if wait_for_backend(timeout_s=10.0):
                log.info("backend reiniciado com sucesso")
                self._consecutive_failures = 0
            else:
                log.error("restart não respondeu /health a tempo")
        except Exception:
            log.exception("restart falhou")
