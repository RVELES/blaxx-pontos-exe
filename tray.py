"""
Tray icon — ícone Blaxx na bandeja do sistema com menu rápido.

Funcionalidades:
  - Menu: Abrir, Status, Abrir pasta de logs, Sair
  - Notificações nativas Windows (toast) via pystray
  - Atualiza status visual quando o backend cai/recupera

Dependências:
  - pystray  (ícone na bandeja)
  - Pillow   (carrega o ícone .ico)

Uso:
    from tray import BlaxxTray
    tray = BlaxxTray(on_open=show_window, on_quit=app_quit)
    tray.run()                  # bloqueia — chame em thread separada
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable, Optional

from config import APP_NAME, APP_VERSION, CONFIG

log = logging.getLogger("blaxx.tray")

try:
    import pystray
    from PIL import Image
    _AVAILABLE = True
except ImportError as e:  # noqa: BLE001
    log.warning("pystray/Pillow indisponíveis (%s) — tray desabilitado", e)
    _AVAILABLE = False


def is_available() -> bool:
    return _AVAILABLE


class BlaxxTray:
    """Ícone Blaxx na system tray. Roda em thread daemon separada."""

    def __init__(
        self,
        on_open: Optional[Callable[[], None]] = None,
        on_quit: Optional[Callable[[], None]] = None,
    ):
        if not _AVAILABLE:
            raise RuntimeError("pystray não disponível — instale com `pip install pystray Pillow`")
        self._on_open = on_open or (lambda: None)
        self._on_quit = on_quit or (lambda: None)
        self._icon: Optional["pystray.Icon"] = None
        self._status_text = "Pronto"
        self._thread: Optional[threading.Thread] = None

    # ----- ações do menu -----
    def _action_open(self, icon, item):  # noqa: ARG002
        log.debug("tray: abrir janela")
        try:
            self._on_open()
        except Exception:
            log.exception("on_open falhou")

    def _action_logs(self, icon, item):  # noqa: ARG002
        path = CONFIG.logs_dir
        log.debug("tray: abrindo pasta de logs %s", path)
        try:
            # Windows: explorer.exe abre a pasta
            os.startfile(str(path))  # type: ignore[attr-defined]
        except AttributeError:
            # macOS/Linux fallback (não deveria acontecer mas seguro)
            subprocess.Popen(["xdg-open", str(path)])
        except Exception:
            log.exception("abrir logs falhou")

    def _action_data(self, icon, item):  # noqa: ARG002
        path = CONFIG.data_dir
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
        except Exception:
            log.exception("abrir data_dir falhou")

    def _action_quit(self, icon, item):  # noqa: ARG002
        log.info("tray: usuário pediu para sair")
        try:
            self._on_quit()
        finally:
            if self._icon:
                self._icon.stop()

    # ----- menu e ícone -----
    def _build_menu(self) -> "pystray.Menu":
        return pystray.Menu(
            pystray.MenuItem(f"Abrir {APP_NAME}", self._action_open, default=True),
            pystray.MenuItem(lambda _i: f"Status: {self._status_text}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Abrir pasta de logs", self._action_logs),
            pystray.MenuItem("Abrir dados do app", self._action_data),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(f"Versão {APP_VERSION}", None, enabled=False),
            pystray.MenuItem("Sair", self._action_quit),
        )

    def _load_icon(self) -> "Image.Image":
        icon_path = CONFIG.icon_path
        if icon_path.exists():
            try:
                return Image.open(str(icon_path))
            except Exception:
                log.exception("falha ao carregar %s — gerando fallback", icon_path)
        # Fallback: gera um ícone simples em runtime
        return _make_fallback_icon()

    # ----- API pública -----
    def run_detached(self) -> threading.Thread:
        """Cria e roda o tray em uma thread daemon. Retorna a thread."""
        def _run():
            try:
                self._icon = pystray.Icon(
                    name=APP_NAME,
                    icon=self._load_icon(),
                    title=f"{APP_NAME} {APP_VERSION}",
                    menu=self._build_menu(),
                )
                log.info("tray iniciado")
                self._icon.run()  # bloqueia até stop()
            except Exception:
                log.exception("tray run falhou")

        t = threading.Thread(target=_run, name="tray", daemon=True)
        t.start()
        self._thread = t
        return t

    def stop(self) -> None:
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                log.exception("tray stop falhou")

    def set_status(self, text: str) -> None:
        """Atualiza o item de status do menu (visível ao clicar no ícone)."""
        self._status_text = text
        if self._icon:
            try:
                self._icon.update_menu()
            except Exception:
                pass

    def notify(self, title: str, message: str) -> None:
        """Mostra toast de notificação do Windows."""
        if self._icon:
            try:
                self._icon.notify(message, title=title)
            except Exception:
                log.exception("notify falhou: %s — %s", title, message)


# ---------------------------------------------------------------------------
# Fallback icon (caso assets/icon.ico não exista)
# ---------------------------------------------------------------------------
def _make_fallback_icon(size: int = 64) -> "Image.Image":
    """Quadrado preto com bolinha verde-limão no meio (logo simplificado)."""
    from PIL import Image as _I, ImageDraw

    img = _I.new("RGBA", (size, size), (10, 10, 10, 255))   # #0A0A0A
    draw = ImageDraw.Draw(img)
    pad = size // 8
    draw.ellipse(
        (pad, pad, size - pad, size - pad),
        fill=(124, 255, 0, 255),                               # #7CFF00
    )
    return img
