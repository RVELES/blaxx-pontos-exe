"""
Gera `assets/icon.ico` com a identidade Blaxx (preto + verde-limão).

Inclui múltiplos tamanhos no mesmo .ico (16, 24, 32, 48, 64, 128, 256)
para o Windows escolher o melhor conforme o contexto (taskbar, atalho,
explorer, alt+tab, ...).

Uso:
    cd blaxx_exe
    python scripts/make_icon.py

Requer: Pillow (`pip install Pillow`)
"""

from __future__ import annotations

import sys
from pathlib import Path

# Permite rodar standalone
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

OUTPUT = ROOT / "assets" / "icon.ico"

# Cores Blaxx (espec. design system)
BLACK = (10, 10, 10, 255)            # #0A0A0A
LIME = (198, 244, 50, 255)           # #C6F432
LIME_DARK = (143, 184, 31, 255)      # #8FB81F
WHITE = (255, 255, 255, 255)


def _render_logo(size: int) -> Image.Image:
    """Desenha o logo Blaxx para um tamanho específico.

    Layout:
      - Fundo preto absoluto com cantos arredondados
      - Letra "B" branca centralizada (Bauhaus-ish)
      - Acento verde-limão na ponta inferior direita (estilo "pontos")
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Fundo arredondado (raio = 18% do tamanho)
    radius = max(2, int(size * 0.18))
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=BLACK)

    # Letra "B" — tenta usar Inter/Arial/qualquer sans bold disponível
    label = "B"
    font = None
    for candidate in ("Arial Bold.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf",
                      "Helvetica.ttc", "Inter-Bold.ttf"):
        try:
            font = ImageFont.truetype(candidate, int(size * 0.62))
            break
        except (OSError, IOError):
            continue
    if font is None:
        font = ImageFont.load_default()

    # Mede e centraliza
    try:
        bbox = draw.textbbox((0, 0), label, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        tx = (size - w) // 2 - bbox[0]
        ty = (size - h) // 2 - bbox[1] - int(size * 0.02)
    except AttributeError:
        # Pillow muito antigo
        w, h = draw.textsize(label, font=font)  # type: ignore[attr-defined]
        tx = (size - w) // 2
        ty = (size - h) // 2
    draw.text((tx, ty), label, font=font, fill=WHITE)

    # Acento verde-limão: círculo pequeno na ponta inferior direita (como o
    # "•" do logotipo "blaxx·pontos")
    dot_d = max(3, int(size * 0.18))
    margin = max(2, int(size * 0.10))
    cx = size - margin - dot_d // 2
    cy = size - margin - dot_d // 2
    draw.ellipse((cx - dot_d // 2, cy - dot_d // 2, cx + dot_d // 2, cy + dot_d // 2),
                 fill=LIME)

    return img


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    print(f"[icon] gerando {OUTPUT} com tamanhos {sizes}")

    # Pillow escolhe a maior como base e gera as outras automaticamente
    base = _render_logo(256)

    # Salva ICO multi-resolução
    base.save(
        str(OUTPUT),
        format="ICO",
        sizes=[(s, s) for s in sizes],
    )

    # Salva também versões PNG individuais (úteis pro tray fallback e doc)
    out_png_dir = ROOT / "assets" / "icons"
    out_png_dir.mkdir(parents=True, exist_ok=True)
    for s in sizes:
        png_path = out_png_dir / f"icon-{s}.png"
        _render_logo(s).save(str(png_path), format="PNG")

    print(f"[icon] OK — {OUTPUT.stat().st_size} bytes")
    print(f"[icon] PNGs em {out_png_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
