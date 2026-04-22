"""Generate stylized placeholder images for reference_looks.

For each YAML in ai-stylist-starter/config/rules/reference_looks/, renders a
600x800 JPEG per look and writes it to frontend/public/reference_looks/<subtype>/<look_id>.jpg.
Also rewrites /static/reference_looks/... paths in YAML to /reference_looks/...
so the frontend Next.js public/ serves them at the same origin.

These images are functional placeholders — family-coloured gradient + subtype
name + look composition summary. Real photos replace them later. They let the
identity-quiz be demoed and tested end-to-end before content-ops ships.
"""
from __future__ import annotations

from pathlib import Path
import yaml
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
YAML_DIR = ROOT / "ai-stylist-starter" / "config" / "rules" / "reference_looks"
OUTPUT_DIR = ROOT / "frontend" / "public" / "reference_looks"

SUBTYPE_TO_FAMILY = {
    "dramatic": "dramatic",
    "soft_dramatic": "dramatic",
    "flamboyant_natural": "natural",
    "soft_natural": "natural",
    "natural": "natural",
    "dramatic_classic": "classic",
    "soft_classic": "classic",
    "classic": "classic",
    "flamboyant_gamine": "gamine",
    "soft_gamine": "gamine",
    "gamine": "gamine",
    "romantic": "romantic",
    "theatrical_romantic": "romantic",
}

# Two gradient variants per family — we cycle through them per look so luks in
# the same subtype look visually distinct.
FAMILY_GRADIENTS = {
    "dramatic": [("#0F1220", "#1F2540"), ("#2A1A3D", "#08080C"), ("#1B2340", "#07060B")],
    "natural":  [("#5C4A28", "#2E2416"), ("#6B4A2B", "#3A2818"), ("#3E2F1C", "#1E1510")],
    "classic":  [("#6D5F4B", "#3A3224"), ("#8A7A63", "#4D4133"), ("#594B38", "#2C241A")],
    "gamine":   [("#B3261E", "#1A237E"), ("#E7A400", "#0B255C"), ("#0B6E4F", "#7D1C2C")],
    "romantic": [("#A93B5B", "#55203A"), ("#C47389", "#6A324F"), ("#85284A", "#3C1628")],
}

FAMILY_ACCENT = {
    "dramatic": "#E8E5F2",
    "natural":  "#E0C79A",
    "classic":  "#F2E8D4",
    "gamine":   "#FFD76B",
    "romantic": "#F5D3DF",
}


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def draw_gradient(w: int, h: int, top_hex: str, bot_hex: str) -> Image.Image:
    top = hex_to_rgb(top_hex)
    bot = hex_to_rgb(bot_hex)
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        t = y / (h - 1)
        r = int(top[0] * (1 - t) + bot[0] * t)
        g = int(top[1] * (1 - t) + bot[1] * t)
        b = int(top[2] * (1 - t) + bot[2] * t)
        for x in range(w):
            px[x, y] = (r, g, b)
    return img


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        [r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\calibrib.ttf", "DejaVuSans-Bold.ttf"]
        if bold
        else [r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\calibri.ttf", "DejaVuSans.ttf"]
    )
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def wrap_text(text: str, font, max_width: int, draw: ImageDraw.ImageDraw) -> list[str]:
    words = text.split()
    lines: list[str] = []
    line: list[str] = []
    for w in words:
        trial = " ".join(line + [w])
        bb = draw.textbbox((0, 0), trial, font=font)
        if bb[2] - bb[0] <= max_width:
            line.append(w)
        else:
            if line:
                lines.append(" ".join(line))
            line = [w]
    if line:
        lines.append(" ".join(line))
    return lines


def render_look(subtype: str, family: str, look_idx: int, look: dict) -> Image.Image:
    w, h = 600, 800
    gradients = FAMILY_GRADIENTS[family]
    top_hex, bot_hex = gradients[look_idx % len(gradients)]
    img = draw_gradient(w, h, top_hex, bot_hex)
    draw = ImageDraw.Draw(img)
    accent = hex_to_rgb(FAMILY_ACCENT[family])

    # Family badge (top-left)
    badge_font = load_font(16, bold=True)
    badge_text = family.upper()
    bb = draw.textbbox((0, 0), badge_text, font=badge_font)
    bw = bb[2] - bb[0]
    bh = bb[3] - bb[1]
    draw.rectangle([40, 30, 40 + bw + 28, 30 + bh + 18], outline=accent, width=2)
    draw.text((54, 38), badge_text, fill=accent, font=badge_font)

    # Subtype title
    title_font = load_font(38, bold=True)
    subtype_display = subtype.replace("_", " ").title()
    y = 110
    for line in wrap_text(subtype_display, title_font, w - 80, draw):
        draw.text((40, y), line, fill=(255, 255, 255), font=title_font)
        bb = draw.textbbox((0, 0), line, font=title_font)
        y += bb[3] - bb[1] + 6

    # Accent divider
    y += 18
    draw.rectangle([40, y, 120, y + 3], fill=accent)

    # Look name
    y += 28
    look_font = load_font(22, bold=True)
    look_name = look.get("name") or look.get("id") or ""
    for line in wrap_text(str(look_name), look_font, w - 80, draw):
        draw.text((40, y), line, fill=(245, 245, 245), font=look_font)
        bb = draw.textbbox((0, 0), line, font=look_font)
        y += bb[3] - bb[1] + 8

    # Style + season
    y += 16
    tag_font = load_font(16)
    style = look.get("style") or "—"
    season = look.get("season_hint") or "all"
    draw.text((40, y), f"{style}  •  {season}", fill=accent, font=tag_font)
    y += 44

    # Items composition
    header_font = load_font(13, bold=True)
    draw.text((40, y), "СОСТАВ ОБРАЗА", fill=accent, font=header_font)
    y += 28
    item_font = load_font(16)
    items = look.get("items") or []
    for item in items[:7]:
        slot = item.get("slot") or "—"
        requires = item.get("requires") or {}
        cat = requires.get("category", "")
        if isinstance(cat, list):
            cat = cat[0] if cat else ""
        line = f"•  {slot}" + (f"  —  {cat}" if cat else "")
        draw.text((40, y), line[:52], fill=(230, 230, 230), font=item_font)
        y += 26

    # Footer: id (aids debugging in dev)
    foot_font = load_font(11)
    draw.text(
        (40, h - 30),
        f"{subtype} / {look.get('id', 'no-id')}",
        fill=(170, 170, 170),
        font=foot_font,
    )
    return img


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    count = 0
    yaml_paths = sorted(YAML_DIR.glob("*.yaml"))

    for yaml_path in yaml_paths:
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        subtype = data.get("subtype")
        family = SUBTYPE_TO_FAMILY.get(subtype)
        if not family:
            print(f"SKIP {yaml_path.name}: no family mapping for '{subtype}'")
            continue
        subtype_dir = OUTPUT_DIR / subtype
        subtype_dir.mkdir(parents=True, exist_ok=True)

        for idx, look in enumerate(data.get("reference_looks") or []):
            look_id = look.get("id")
            if not look_id:
                continue
            img = render_look(subtype, family, idx, look)
            target = subtype_dir / f"{look_id}.jpg"
            img.save(target, "JPEG", quality=85, optimize=True)
            count += 1

    # Normalize image_url paths in YAMLs (simple string replacement preserves
    # comments and block styles that yaml.safe_dump would flatten).
    yamls_changed = 0
    for yaml_path in yaml_paths:
        text = yaml_path.read_text(encoding="utf-8")
        new_text = text.replace("/static/reference_looks/", "/reference_looks/")
        if new_text != text:
            yaml_path.write_text(new_text, encoding="utf-8")
            yamls_changed += 1

    print(f"Rendered {count} images into {OUTPUT_DIR}")
    print(f"Rewrote image_url paths in {yamls_changed} YAMLs")


if __name__ == "__main__":
    main()
