from pathlib import Path

import pytest

from wimm.core.os_release import (
    DistroFamily,
    distro_family,
    parse_os_release,
    read_os_release,
)

UBUNTU = 'NAME="Ubuntu"\nID=ubuntu\nID_LIKE=debian\nVERSION_ID="24.04"\n'
MINT = 'NAME="Linux Mint"\nID=linuxmint\nID_LIKE="ubuntu debian"\n'
FEDORA = "NAME='Fedora Linux'\nID=fedora\nVERSION_ID=44\n"
ARCH = 'NAME="Arch Linux"\nID=arch\n'
MANJARO = "ID=manjaro\nID_LIKE=arch\n"
DEBIAN = 'NAME="Debian GNU/Linux"\nID=debian\n'
NIXOS = "ID=nixos\n"


@pytest.mark.parametrize(
    ("text", "family"),
    [
        (UBUNTU, DistroFamily.UBUNTU),
        (MINT, DistroFamily.UBUNTU),
        (FEDORA, DistroFamily.FEDORA),
        (ARCH, DistroFamily.ARCH),
        (MANJARO, DistroFamily.ARCH),
        (DEBIAN, DistroFamily.DEBIAN),
        (NIXOS, DistroFamily.OTHER),
        ("", DistroFamily.OTHER),
    ],
)
def test_distro_family_follows_id_and_id_like(text: str, family: DistroFamily) -> None:
    assert distro_family(text=text) is family


def test_parse_strips_quotes_and_skips_comments_and_blank_lines() -> None:
    text = "# comment\n\nID=\"fedora\"\nID_LIKE='rhel centos'\nbroken line\n"
    assert parse_os_release(text=text) == {"ID": "fedora", "ID_LIKE": "rhel centos"}


def test_parse_keeps_the_last_value_of_a_repeated_key() -> None:
    assert parse_os_release(text="ID=arch\nID=fedora\n")["ID"] == "fedora"


def test_read_returns_the_file_text(tmp_path: Path) -> None:
    path = tmp_path / "os-release"
    path.write_text(FEDORA, encoding="utf-8")
    assert read_os_release(paths=(path,)) == FEDORA


def test_read_of_a_missing_file_is_empty_and_gives_other(tmp_path: Path) -> None:
    text = read_os_release(paths=(tmp_path / "absent", tmp_path / "absent-too"))
    assert text == ""
    assert distro_family(text=text) is DistroFamily.OTHER


def test_read_of_a_non_utf8_file_is_empty(tmp_path: Path) -> None:
    path = tmp_path / "os-release"
    path.write_bytes(b"ID=\xff\xfe\n")
    assert read_os_release(paths=(path,)) == ""


def test_read_falls_back_to_usr_lib_when_etc_is_missing(tmp_path: Path) -> None:
    # freedesktop os-release: /etc/os-release first, /usr/lib/os-release when it is absent.
    fallback = tmp_path / "usr-lib-os-release"
    fallback.write_text(FEDORA, encoding="utf-8")

    assert read_os_release(paths=(tmp_path / "etc-os-release", fallback)) == FEDORA
