"""
Build helper — gera o BlaxxPontos.exe para Windows.

Uso (no Windows, com venv ativado):
    python build.py                       # build padrão (--clean --noconfirm)
    python build.py --installer           # também monta installer Inno Setup
    python build.py --onefile             # gera single-file .exe (mais lento)

Saída:
    dist/BlaxxPontos/BlaxxPontos.exe      # modo onedir (default)
    dist/BlaxxPontos.exe                  # modo onefile (com --onefile)
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()


def clean() -> None:
    for d in ("build", "dist"):
        p = ROOT / d
        if p.exists():
            print(f"[clean] removendo {p}")
            shutil.rmtree(p, ignore_errors=True)


def run_pyinstaller(args: argparse.Namespace) -> int:
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
    ]
    if args.clean:
        cmd.append("--clean")

    if args.onefile:
        # Modo single-file — gera 1 .exe gigante (~100MB) que extrai em %TEMP%
        cmd += [
            "--onefile",
            "--windowed",
            "--name", "BlaxxPontos",
            "--add-data", f"{ROOT/'renderer'};renderer",
            "--add-data", f"{ROOT/'backend'};backend",
            "--paths", str(ROOT / "backend"),
        ]
        # hiddenimports replicados aqui pois não estamos usando o .spec
        for mod in (
            "app", "app.api", "app.config", "app.extensions", "app.models",
            "app.pix.mock", "app.pix.mercadopago", "app.pix.provider",
            "app.services", "psycopg",
            "sqlalchemy.dialects.sqlite", "sqlalchemy.dialects.postgresql",
            "argon2", "pyotp", "qrcode", "phonenumbers",
        ):
            cmd += ["--hidden-import", mod]
        ico = ROOT / "assets" / "icon.ico"
        if ico.exists():
            cmd += ["--icon", str(ico)]
        cmd.append(str(ROOT / "main.py"))
    else:
        # Modo onedir via .spec (recomendado — startup mais rápido)
        cmd.append(str(ROOT / "blaxx_exe.spec"))

    print("[build] $", " ".join(cmd))
    return subprocess.call(cmd, cwd=str(ROOT))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--no-clean", dest="clean", action="store_false",
                   help="não apaga dist/ e build/ antes")
    p.add_argument("--onefile", action="store_true",
                   help="gera um único .exe (mais lento ao abrir)")
    p.add_argument("--installer", action="store_true",
                   help="depois do build, monta installer com Inno Setup (precisa do iscc.exe no PATH)")
    args = p.parse_args(argv)

    if args.clean:
        clean()

    rc = run_pyinstaller(args)
    if rc != 0:
        print(f"[build] PyInstaller falhou (rc={rc})")
        return rc

    print("[build] OK")
    if args.onefile:
        print("[build] arquivo: dist/BlaxxPontos.exe")
    else:
        print("[build] pasta:  dist/BlaxxPontos/")
        print("[build] binário: dist/BlaxxPontos/BlaxxPontos.exe")

    if args.installer:
        iss = ROOT / "installer.iss"
        if not iss.exists():
            print("[installer] installer.iss não existe — pule este passo ou crie o script.")
        else:
            print("[installer] rodando Inno Setup compiler…")
            rc = subprocess.call(["iscc", str(iss)], cwd=str(ROOT))
            if rc == 0:
                print("[installer] OK — output em dist/installer/")
            else:
                print(f"[installer] iscc falhou (rc={rc})")
                return rc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
