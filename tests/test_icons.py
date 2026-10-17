import base64
import io
import re

import pytest
from PIL import Image

from scripts import build_icons

EMBEDDED_PNG = re.compile(r'href="data:image/png;base64,([A-Za-z0-9+/=]+)"')
OPAQUE = 255
TRANSPARENT = 0


def status_image(state: str) -> Image.Image:
    path = build_icons.HICOLOR / "scalable" / "status" / f"wimm-{state}.svg"
    match = EMBEDDED_PNG.search(path.read_text(encoding="utf-8"))
    assert match is not None, path
    return Image.open(io.BytesIO(base64.b64decode(match.group(1)))).convert("RGBA")


@pytest.mark.parametrize("size", build_icons.APP_SIZES)
def test_app_icon_exists_at_exact_size_with_transparent_margin(size: int) -> None:
    path = build_icons.HICOLOR / f"{size}x{size}" / "apps" / f"{build_icons.APP_ID}.png"
    image = Image.open(path).convert("RGBA")
    assert image.size == (size, size)
    assert image.getpixel((0, 0))[3] == TRANSPARENT
    assert max(image.getchannel("A").tobytes()) == OPAQUE


def test_build_deb_installs_every_rendered_app_size() -> None:
    script = (build_icons.ROOT / "scripts" / "build_deb.sh").read_text(encoding="utf-8")
    sizes = " ".join(str(size) for size in build_icons.APP_SIZES)
    assert f"for size in {sizes}; do" in script


def test_status_icons_share_the_logo_and_differ_only_by_badge() -> None:
    normal, warning, critical = (status_image(state=s) for s in ("normal", "warning", "critical"))
    corner = (build_icons.STATUS_RASTER * 7 // 8,) * 2
    top_left = (0, 0, build_icons.STATUS_RASTER // 2, build_icons.STATUS_RASTER // 2)
    assert normal.crop(top_left).tobytes() == warning.crop(top_left).tobytes()
    assert warning.getpixel(corner) != normal.getpixel(corner)
    assert warning.getpixel(corner) != critical.getpixel(corner)


def test_add_badge_paints_the_corner_without_touching_the_input() -> None:
    blank = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    badge = build_icons.BADGES["critical"]
    assert badge is not None
    result = build_icons.add_badge(image=blank, badge=badge)
    assert result.getpixel((38, 48)) == badge.fill
    assert result.getpixel((5, 5)) == (0, 0, 0, 0)
    assert max(blank.getchannel("A").tobytes()) == TRANSPARENT
