"""
Setup de logging do Blaxx Pontos · Windows.

- Console handler (StreamHandler) com formato curto
- File handler rotativo em `%APPDATA%\\Blaxx Pontos\\logs\\app.log`
  rotaciona a cada 5MB, mantém 5 backups
- Configura também o logger do Flask/Werkzeug para sair no mesmo lugar

Uso:
    from logging_setup import init_logging
    init_logging()
    log = logging.getLogger(__name__)
"""

from __future__ import annotations

import logging
import logging.handlers
import sys

from config import CONFIG


_INITIALIZED = False


def init_logging() -> logging.Logger:
    """Configura logging global. Idempotente — pode chamar várias vezes."""
    global _INITIALIZED
    if _INITIALIZED:
        return logging.getLogger("blaxx")

    log_file = CONFIG.logs_dir / "app.log"
    level = getattr(logging, CONFIG.logging.level.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    # Remove handlers padrões pra evitar duplicação
    for h in list(root.handlers):
        root.removeHandler(h)

    fmt_console = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s :: %(message)s",
        datefmt="%H:%M:%S",
    )
    fmt_file = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s [%(threadName)s] :: %(message)s"
    )

    # Console — só fica visível em dev (modo .exe windowed não tem console)
    console = logging.StreamHandler(stream=sys.stderr)
    console.setLevel(level)
    console.setFormatter(fmt_console)
    root.addHandler(console)

    # Arquivo rotativo — sempre ativo
    file_h = logging.handlers.RotatingFileHandler(
        str(log_file),
        maxBytes=CONFIG.logging.file_max_bytes,
        backupCount=CONFIG.logging.file_backup_count,
        encoding="utf-8",
    )
    file_h.setLevel(level)
    file_h.setFormatter(fmt_file)
    root.addHandler(file_h)

    # Silencia barulho de libs verbosas
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.WARNING)

    _INITIALIZED = True

    log = logging.getLogger("blaxx")
    log.info("=" * 60)
    log.info("Blaxx Pontos %s — log iniciado", _version())
    log.info("Log file: %s", log_file)
    log.info("Data dir: %s", CONFIG.data_dir)
    log.info("=" * 60)
    return log


def _version() -> str:
    from config import APP_VERSION
    return APP_VERSION
