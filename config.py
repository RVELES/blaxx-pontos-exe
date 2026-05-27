"""
Blaxx Pontos · configuração central do app Windows.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


APP_NAME = "Blaxx Pontos"
APP_VERSION = "0.1.0"
APP_ID = "com.blaxx.pontos.windows"

# URL de produção do backend — migrado do Fly.io pra Render.com em 2026-05-27.
# Mesmo banco Neon Postgres compartilhado por Web/Mac/iOS/Windows.
# Override via env var BLAXX_BACKEND_URL se quiser apontar pra staging/Fly.
PRODUCTION_BACKEND_URL = "https://blaxx-pontos-backend.onrender.com"


def app_root() -> Path:
    """Raiz dos assets — funciona em dev e empacotado pelo PyInstaller."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).parent.resolve()


def user_data_dir() -> Path:
    """Pasta persistente do usuário: %APPDATA%\\Blaxx Pontos\\."""
    base = os.environ.get("APPDATA") or str(Path.home())
    p = Path(base) / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def logs_dir() -> Path:
    p = user_data_dir() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path() -> Path:
    return user_data_dir() / "blaxx.db"


@dataclass(frozen=True)
class WindowConfig:
    title: str = APP_NAME
    width: int = 1180
    height: int = 780
    min_width: int = 980
    min_height: int = 640
    background_color: str = "#0A0A0A"


@dataclass(frozen=True)
class BackendConfig:
    """Configuração do backend (modos remoto/local)."""
    host: str = field(default_factory=lambda: os.environ.get("BLAXX_BACKEND_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.environ.get("BLAXX_BACKEND_PORT", "5050")))
    health_timeout_s: float = 20.0
    health_check_interval_s: float = 10.0
    health_failure_threshold: int = 3

    remote_url: str = field(default_factory=lambda: os.environ.get(
        "BLAXX_BACKEND_URL", PRODUCTION_BACKEND_URL
    ).rstrip("/"))
    remote_health_timeout_s: float = 8.0

    @property
    def local_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def url(self) -> str:
        return self.local_url

    @property
    def health_url(self) -> str:
        return f"{self.local_url}/health"

    @property
    def remote_health_url(self) -> str:
        return f"{self.remote_url}/health"


@dataclass(frozen=True)
class GoogleConfig:
    """Google Sign-In (Desktop App OAuth Client ID).

    O Client ID e' publico por design (nao e' segredo); seguranca vem do
    PKCE + validacao do ID Token no backend. Configure em:
    https://console.cloud.google.com/apis/credentials
    Tipo: 'Desktop app' (nao Web!), pra suportar redirect 127.0.0.1.
    """
    client_id: str = field(default_factory=lambda: os.environ.get(
        "BLAXX_GOOGLE_CLIENT_ID", ""
    ).strip())
    # client_secret e' opcional pro tipo "Desktop app" + PKCE. Se setado,
    # eh enviado no token exchange (alguns Client IDs exigem).
    client_secret: str = field(default_factory=lambda: os.environ.get(
        "BLAXX_GOOGLE_CLIENT_SECRET", ""
    ).strip())

    @property
    def configured(self) -> bool:
        return bool(self.client_id)


@dataclass(frozen=True)
class LoggingConfig:
    level: str = field(default_factory=lambda: os.environ.get("BLAXX_LOG_LEVEL", "INFO"))
    file_max_bytes: int = 5 * 1024 * 1024
    file_backup_count: int = 5


@dataclass(frozen=True)
class AppConfig:
    window: WindowConfig = field(default_factory=WindowConfig)
    backend: BackendConfig = field(default_factory=BackendConfig)
    google: GoogleConfig = field(default_factory=GoogleConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    @property
    def root(self) -> Path:
        return app_root()

    @property
    def backend_dir(self) -> Path:
        return self.root / "backend"

    @property
    def renderer_dir(self) -> Path:
        return self.root / "renderer"

    @property
    def icon_path(self) -> Path:
        return self.root / "assets" / "icon.ico"

    @property
    def data_dir(self) -> Path:
        return user_data_dir()

    @property
    def logs_dir(self) -> Path:
        return logs_dir()

    @property
    def db_url(self) -> str:
        return os.environ.get(
            "DATABASE_URL",
            f"sqlite:///{db_path().as_posix()}",
        )


# Singleton
CONFIG = AppConfig()
