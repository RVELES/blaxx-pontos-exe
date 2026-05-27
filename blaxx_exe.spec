# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — gera o .exe distribuível do Blaxx Pontos para Windows.

Gera:
  dist/BlaxxPontos/BlaxxPontos.exe   (modo onedir, recomendado)
  + dist/BlaxxPontos/<libs e assets>

Uso:
  pyinstaller blaxx_exe.spec --noconfirm --clean
"""

from pathlib import Path

block_cipher = None
ROOT = Path(SPECPATH)

a = Analysis(
    ['main.py'],
    pathex=[str(ROOT), str(ROOT / 'backend')],
    binaries=[],
    datas=[
        # Renderer (HTML/CSS/JS) — embarcado dentro do .exe (sys._MEIPASS)
        (str(ROOT / 'renderer'), 'renderer'),
        # Backend Python + recursos estáticos
        (str(ROOT / 'backend'),  'backend'),
        # Assets (ícone .ico para tray + janela)
        (str(ROOT / 'assets'),   'assets'),
    ],
    hiddenimports=[
        # Módulos do app Windows
        'config',
        'logging_setup',
        'backend_runner',
        'tray',
        'backend_proxy',
        # Tray icon
        'pystray',
        'pystray._win32',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        # Flask blueprints — PyInstaller não detecta os imports dinâmicos
        'app',
        'app.api',
        'app.api.admin',
        'app.api.auth',
        'app.api.benefits',
        'app.api.campaigns',
        'app.api.notifications',
        'app.api.partners',
        'app.api.pix',
        'app.api.redeem',
        'app.api.transfer',
        'app.api.wallet',
        'app.config',
        'app.extensions',
        'app.models',
        'app.pix',
        'app.pix.mercadopago',
        'app.pix.mock',
        'app.pix.provider',
        'app.security',
        'app.services',
        'app.services.audit',
        'app.services.mailer',
        'app.services.purchase',
        'app.services.redeem',
        'app.services.transfer',
        'app.services.wallet',
        # Drivers de DB e libs que PyInstaller às vezes ignora
        'psycopg',
        'sqlalchemy.dialects.sqlite',
        'sqlalchemy.dialects.postgresql',
        'argon2',
        'argon2.low_level',
        'pyotp',
        'qrcode',
        'qrcode.image.pil',
        'phonenumbers',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Reduz tamanho — não usamos esses módulos pesados
        'matplotlib',
        'numpy',
        'pandas',
        'pytest',
        'tkinter',
        'unittest',
        'PIL.ImageTk',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='BlaxxPontos',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,           # comprime binários (instala upx separadamente se quiser)
    console=False,      # janela GUI, sem console preto
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / 'assets' / 'icon.ico') if (ROOT / 'assets' / 'icon.ico').exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='BlaxxPontos',
)
