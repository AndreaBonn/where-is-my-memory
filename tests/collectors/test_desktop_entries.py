import logging
import os
import shutil
from pathlib import Path

import pytest

from wimm.collectors.desktop_entries import (
    DesktopEntry,
    DesktopEntryIndex,
    default_directories,
    directory_stamp,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "desktop"


def test_desktop_entries_alias_translation_and_categories(tmp_path: Path) -> None:
    for path in FIXTURES.iterdir():
        shutil.copy(src=path, dst=tmp_path / path.name)
    (tmp_path / "broken.desktop").write_text("[invalid")
    index = DesktopEntryIndex(directories=(tmp_path,))
    result = index.collect()
    assert result.error is None
    assert result.data["editor"] == DesktopEntry(
        name="Editor italiano", categories=("Development", "IDE")
    )
    assert result.data["Code"] == result.data["editor"]
    assert result.data["terminal"] == DesktopEntry(
        name="Terminal", categories=("System", "TerminalEmulator")
    )
    assert "broken" not in result.data


def test_desktop_cache_invalidated_by_directory_mtime(tmp_path: Path) -> None:
    target = tmp_path / "app.desktop"
    target.write_text("[Desktop Entry]\nName=Before\n")
    index = DesktopEntryIndex(directories=(tmp_path,))
    assert index.collect().data["app"].name == "Before"
    directory_mtime = tmp_path.stat().st_mtime_ns
    file_mtime = target.stat().st_mtime_ns
    target.write_text("[Desktop Entry]\nName=After\n")
    os.utime(path=target, ns=(file_mtime + 1, file_mtime + 1))
    assert tmp_path.stat().st_mtime_ns == directory_mtime
    assert index.collect().data["app"].name == "After"
    stamp = tmp_path.stat().st_mtime_ns + 1_000_000_000
    os.utime(path=tmp_path, ns=(stamp, stamp))
    assert index.collect().data["app"].name == "After"
    target.unlink()
    assert index.collect().data == {}


def test_missing_directory_can_appear(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    index = DesktopEntryIndex(directories=(missing,))
    assert index.collect().data == {}
    missing.mkdir()
    (missing / "new.desktop").write_text("[Desktop Entry]\nName=New\n")
    assert index.collect().data["new"].name == "New"


def test_unreadable_directory_is_skipped_and_the_others_are_kept(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    readable = tmp_path / "readable"
    readable.mkdir()
    (readable / "good.desktop").write_text("[Desktop Entry]\nName=Good\n")
    unreadable = tmp_path / "file"
    unreadable.touch()
    with caplog.at_level(level=logging.WARNING):
        result = DesktopEntryIndex(directories=(unreadable, readable)).collect()
    assert dict(result.data) == {"good": DesktopEntry(name="Good", categories=())}
    assert str(unreadable) in caplog.text
    assert "WARNING" in caplog.text


@pytest.mark.integration
def test_real_gnome_terminal() -> None:
    result = DesktopEntryIndex().collect()
    assert result.error is None
    assert result.data["org.gnome.Terminal"].name
    assert "TerminalEmulator" in result.data["org.gnome.Terminal"].categories


def test_bad_encoding_preserves_valid_entries(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "good.desktop").write_text("[Desktop Entry]\nName=Good\n", encoding="utf-8")
    bad = tmp_path / "bad.desktop"
    bad.write_bytes(b"[Desktop Entry]\nName=\xff\n")
    with caplog.at_level(level=logging.DEBUG):
        result = DesktopEntryIndex(directories=(tmp_path,)).collect()
    assert result.error is None
    assert dict(result.data) == {"good": DesktopEntry(name="Good", categories=())}
    assert str(bad) in caplog.text


@pytest.mark.skipif(os.getuid() == 0, reason="Root can read mode 000 files")
def test_unreadable_file_preserves_valid_entries(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "good.desktop").write_text("[Desktop Entry]\nName=Good\n", encoding="utf-8")
    bad = tmp_path / "bad.desktop"
    bad.write_text("[Desktop Entry]\nName=Bad\n", encoding="utf-8")
    bad.chmod(mode=0)
    try:
        with caplog.at_level(level=logging.DEBUG):
            result = DesktopEntryIndex(directories=(tmp_path,)).collect()
        assert result.error is None
        assert dict(result.data) == {"good": DesktopEntry(name="Good", categories=())}
        assert str(bad) in caplog.text
    finally:
        bad.chmod(mode=0o600)


def test_user_override_wins_default_search_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from wimm.collectors import desktop_entries

    system = tmp_path / "system"
    system.mkdir()
    monkeypatch.setattr(
        target=desktop_entries, name="SYSTEM_DIRECTORIES", value=(system, system, system)
    )
    user = Path.home() / ".local/share/applications"
    user.mkdir(parents=True)
    for directory, name in ((system, "System"), (user, "User")):
        (directory / "app.desktop").write_text(f"[Desktop Entry]\nName={name}\n")
    assert default_directories()[-1] == user
    assert DesktopEntryIndex().collect().data["app"].name == "User"


@pytest.mark.parametrize("alias_stem", ["a-alias", "z-alias"])
def test_alias_never_replaces_real_stem(tmp_path: Path, alias_stem: str) -> None:
    (tmp_path / "real.desktop").write_text("[Desktop Entry]\nName=Real\n")
    (tmp_path / f"{alias_stem}.desktop").write_text(
        "[Desktop Entry]\nName=Alias\nStartupWMClass=real\n"
    )
    result = DesktopEntryIndex(directories=(tmp_path,)).collect()
    assert result.data["real"].name == "Real"
    assert result.data[alias_stem].name == "Alias"


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        ("Name=Base\nName[it]=Italiano\nName[it_IT]=Italia", "Italia"),
        ("Name=Base\nName[it]=Italiano", "Italiano"),
        ("Name=First\nName=Last", "Last"),
    ],
)
def test_locale_and_duplicate_keys(tmp_path: Path, names: str, expected: str) -> None:
    (tmp_path / "app.desktop").write_text(f"[Desktop Entry]\n{names}\n", encoding="utf-8")
    result = DesktopEntryIndex(directories=(tmp_path,)).collect()
    assert result.error is None
    assert result.data["app"].name == expected


def test_directory_stamp_stats_each_desktop_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "app.desktop"
    target.touch()
    (tmp_path / "ignored.txt").touch()
    expected = (tmp_path.stat().st_mtime_ns, target.stat().st_mtime_ns)
    original_stat = Path.stat
    calls: list[Path] = []

    def stat(path: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        calls.append(path)
        return original_stat(path, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(target=Path, name="stat", value=stat)
    assert directory_stamp(path=tmp_path) == expected
    assert calls.count(target) == 1
    assert tmp_path / "ignored.txt" not in calls
