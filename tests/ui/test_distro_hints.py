import pytest

from wimm.core.os_release import DistroFamily
from wimm.ui.distro_hints import TrayHint, tray_hint

PACKAGE = "gnome-shell-extension-appindicator"


def test_ubuntu_keeps_the_preinstalled_extension_text() -> None:
    hint = tray_hint(family=DistroFamily.UBUNTU)
    assert hint.title == "L'icona nella barra richiede l'estensione AppIndicator di Ubuntu"
    assert "«Ubuntu AppIndicators»" in hint.steps
    assert hint.command == "gnome-extensions enable ubuntu-appindicators@ubuntu.com"


@pytest.mark.parametrize(
    ("family", "command"),
    [
        (DistroFamily.FEDORA, f"sudo dnf install {PACKAGE}"),
        (DistroFamily.ARCH, f"sudo pacman -S {PACKAGE}"),
        (DistroFamily.DEBIAN, f"sudo apt install {PACKAGE}"),
    ],
)
def test_other_families_install_the_package_with_their_manager(
    family: DistroFamily, command: str
) -> None:
    hint = tray_hint(family=family)
    assert hint.command == command
    assert "Ubuntu" not in hint.title
    assert "Estensioni" in hint.steps


def test_unknown_distribution_points_to_the_extension_site() -> None:
    hint = tray_hint(family=DistroFamily.OTHER)
    assert "AppIndicator and KStatusNotifierItem Support" in hint.steps
    assert "extensions.gnome.org" in hint.steps
    assert hint.command is None


def test_every_family_has_a_distinct_hint() -> None:
    hints: list[TrayHint] = [tray_hint(family=family) for family in DistroFamily]
    assert len({(h.title, h.steps, h.command) for h in hints}) == len(DistroFamily)
