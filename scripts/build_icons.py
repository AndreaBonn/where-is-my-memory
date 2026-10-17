"""Render every icon the app exposes from the single master logo in assets/logo.

Run with `uv run python scripts/build_icons.py` after changing the master; the output in
data/icons is committed, so packaging never needs Pillow.
"""

import base64
import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "assets" / "logo" / "wimm-logo.png"
HICOLOR = ROOT / "data" / "icons" / "hicolor"
APP_ID = "io.github.wimm.WhereIsMyMemory"
APP_SIZES = (16, 24, 32, 48, 64, 128, 256, 512)
STATUS_RASTER = 128
BADGE_RATIO = 0.5
MARK_WIDTH_RATIO = 0.16
INK = (255, 255, 255, 255)


@dataclass(frozen=True)
class Badge:
    """Colour of the tray-state badge (Adwaita warning and error palettes)."""

    fill: tuple[int, int, int, int]
    ring: tuple[int, int, int, int]


BADGES: dict[str, Badge | None] = {
    "normal": None,
    "warning": Badge(fill=(229, 165, 10, 255), ring=(255, 255, 255, 255)),
    "critical": Badge(fill=(224, 27, 36, 255), ring=(255, 255, 255, 255)),
}


def resize(image: Image.Image, size: int) -> Image.Image:
    """Downscale with Lanczos, the filter that keeps small icons sharp."""
    return image.resize((size, size), Image.Resampling.LANCZOS)


def add_badge(image: Image.Image, badge: Badge) -> Image.Image:
    """Return a copy with a round "!" badge in the bottom-right corner."""
    result = image.copy()
    side = result.width
    diameter = round(side * BADGE_RATIO)
    box = (side - diameter, side - diameter, side - 1, side - 1)
    draw = ImageDraw.Draw(result)
    ring = max(1, diameter // 12)
    draw.ellipse(box, fill=badge.ring)
    inner = (box[0] + ring, box[1] + ring, box[2] - ring, box[3] - ring)
    draw.ellipse(inner, fill=badge.fill)
    centre = side - diameter / 2
    width = diameter * MARK_WIDTH_RATIO
    top, bottom = side - diameter * 0.78, side - diameter * 0.42
    draw.rounded_rectangle(
        (centre - width / 2, top, centre + width / 2, bottom), radius=width / 2, fill=INK
    )
    dot = side - diameter * 0.26
    draw.ellipse(
        (centre - width / 2, dot - width / 2, centre + width / 2, dot + width / 2), fill=INK
    )
    return result


def svg_wrapping(image: Image.Image) -> str:
    """Wrap a raster in an SVG so it installs under hicolor/scalable like a vector icon."""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    data = base64.b64encode(buffer.getvalue()).decode("ascii")
    side = image.width
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{side}" height="{side}" '
        f'viewBox="0 0 {side} {side}">\n'
        f'  <image width="{side}" height="{side}" href="data:image/png;base64,{data}"/>\n'
        "</svg>\n"
    )


def write_app_icons(master: Image.Image) -> None:
    for size in APP_SIZES:
        target = HICOLOR / f"{size}x{size}" / "apps" / f"{APP_ID}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        resize(image=master, size=size).save(target, format="PNG", optimize=True)


def write_status_icons(master: Image.Image) -> None:
    base = resize(image=master, size=STATUS_RASTER)
    folder = HICOLOR / "scalable" / "status"
    folder.mkdir(parents=True, exist_ok=True)
    for state, badge in BADGES.items():
        image = base if badge is None else add_badge(image=base, badge=badge)
        (folder / f"wimm-{state}.svg").write_text(svg_wrapping(image=image), encoding="utf-8")


def main() -> None:
    master = Image.open(MASTER).convert("RGBA")
    write_app_icons(master=master)
    write_status_icons(master=master)


if __name__ == "__main__":
    main()
