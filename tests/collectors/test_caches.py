import logging
import os
from pathlib import Path

import pytest

from wimm.collectors.cache_table import read_cache_table
from wimm.collectors.caches import collect_caches
from wimm.model.disk import CacheEntry, CacheKind

RELATIVE = {
    CacheKind.UV: ".cache/uv",
    CacheKind.NPM: ".npm/_cacache",
    CacheKind.PIP: ".cache/pip",
    CacheKind.TRASH: ".local/share/Trash",
    CacheKind.THUMBNAILS: ".cache/thumbnails",
}


def _make_cache(home: Path, kind: CacheKind, payload: int = 5000) -> Path:
    folder = home / RELATIVE[kind]
    folder.mkdir(parents=True)
    (folder / "data.bin").write_bytes(b"x" * payload)
    return folder


def _collect(
    home: Path, tmp_path: Path, environ: dict[str, str] | None = None
) -> dict[CacheKind, CacheEntry]:
    table = read_cache_table(environ=environ or {}, home=home, roots=())
    entries = collect_caches(table=table, cache_dir=tmp_path / "sizes", sleep=lambda _s: None)
    return {entry.kind: entry for entry in entries}


def _blocks(*paths: Path) -> int:
    return sum(os.lstat(path).st_blocks * 512 for path in paths)


def test_collect_caches_reports_all_five_kinds_with_sizes(tmp_path: Path) -> None:
    home = tmp_path / "fakehome"
    folders = {
        kind: _make_cache(home, kind, payload=4096 * (index + 1))
        for index, kind in enumerate(RELATIVE)
    }
    found = _collect(home, tmp_path)
    assert set(found) == set(RELATIVE)
    for kind, folder in folders.items():
        assert found[kind].path == str(folder)
        assert found[kind].size == _blocks(folder, folder / "data.bin")


def test_collect_caches_missing_folder_gives_no_entry(tmp_path: Path) -> None:
    home = tmp_path / "fakehome"
    _make_cache(home, CacheKind.UV)
    assert set(_collect(home, tmp_path)) == {CacheKind.UV}


def test_collect_caches_empty_home_gives_nothing(tmp_path: Path) -> None:
    home = tmp_path / "fakehome"
    home.mkdir()
    assert _collect(home, tmp_path) == {}


def test_collect_caches_symlinked_folder_is_skipped(tmp_path: Path) -> None:
    home = tmp_path / "fakehome"
    target = tmp_path / "elsewhere"
    target.mkdir()
    (target / "big.bin").write_bytes(b"x" * 50000)
    link = home / RELATIVE[CacheKind.PIP]
    link.parent.mkdir(parents=True)
    link.symlink_to(target, target_is_directory=True)
    _make_cache(home, CacheKind.UV)
    found = _collect(home, tmp_path)
    assert CacheKind.PIP not in found
    assert CacheKind.UV in found


def test_collect_caches_fingerprint_is_lstat_of_folder(tmp_path: Path) -> None:
    home = tmp_path / "fakehome"
    folder = _make_cache(home, CacheKind.TRASH)
    entry = _collect(home, tmp_path)[CacheKind.TRASH]
    info = os.lstat(folder)
    assert (entry.st_ino, entry.st_dev) == (info.st_ino, info.st_dev)


def test_collect_caches_hard_links_counted_once(tmp_path: Path) -> None:
    home = tmp_path / "fakehome"
    folder = _make_cache(home, CacheKind.NPM, payload=8192)
    os.link(src=folder / "data.bin", dst=folder / "alias.bin")
    entry = _collect(home, tmp_path)[CacheKind.NPM]
    assert entry.size == _blocks(folder, folder / "data.bin")


def test_collect_caches_file_instead_of_folder_is_skipped(tmp_path: Path) -> None:
    home = tmp_path / "fakehome"
    path = home / RELATIVE[CacheKind.UV]
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not a folder")
    _make_cache(home, CacheKind.THUMBNAILS)
    found = _collect(home, tmp_path)
    assert CacheKind.UV not in found
    assert CacheKind.THUMBNAILS in found


def test_collect_caches_finds_the_new_types_where_the_home_and_xdg_put_them(
    tmp_path: Path,
) -> None:
    home = tmp_path / "fakehome"
    xdg = home / "xdg" / "cache"
    for folder in (xdg / "go-build", xdg / "JetBrains", home / ".gradle" / "caches"):
        folder.mkdir(parents=True)
        (folder / "data.bin").write_bytes(b"x" * 5000)
    (home / ".cache").mkdir()
    (home / ".cache" / "go-build").mkdir()  # the default place: XDG_CACHE_HOME moved it

    found = _collect(home, tmp_path, environ={"XDG_CACHE_HOME": str(xdg)})

    assert set(found) == {CacheKind.GO_BUILD, CacheKind.JETBRAINS, CacheKind.GRADLE}
    assert found[CacheKind.GO_BUILD].path == str(xdg / "go-build")
    assert found[CacheKind.GRADLE].path == str(home / ".gradle" / "caches")


def test_collect_caches_follows_a_tool_variable_only_when_the_folder_is_the_tools(
    tmp_path: Path,
) -> None:
    home = tmp_path / "fakehome"
    tagged, plain = home / "tools" / "bun", home / "docs" / "yarn"
    for folder in (tagged, plain):
        folder.mkdir(parents=True)
        (folder / "data.bin").write_bytes(b"x" * 5000)
    (tagged / "CACHEDIR.TAG").write_text("Signature: 8a477f597d28d172789f06886806bc55\n")
    environ = {"BUN_INSTALL_CACHE_DIR": str(tagged), "YARN_CACHE_FOLDER": str(plain)}

    found = _collect(home, tmp_path, environ=environ)

    assert set(found) == {CacheKind.BUN}
    assert found[CacheKind.BUN].path == str(tagged)


def test_collect_caches_unstatable_folder_is_skipped_with_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    home = tmp_path / "fakehome"
    denied = _make_cache(home, CacheKind.UV)
    _make_cache(home, CacheKind.THUMBNAILS)
    table = read_cache_table(environ={}, home=home, roots=())
    real_lstat = os.lstat

    def lstat(path: object, *args: object, **kwargs: object) -> os.stat_result:
        if str(path) == str(denied):
            raise PermissionError("denied")
        return real_lstat(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(target=os, name="lstat", value=lstat)
    with caplog.at_level(logging.WARNING):
        entries = collect_caches(table=table, cache_dir=tmp_path / "sizes", sleep=lambda _s: None)

    assert {entry.kind for entry in entries} == {CacheKind.THUMBNAILS}
    assert any(
        record.levelno == logging.WARNING and "Cannot stat cache" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_collect_caches_still_reports_a_folder_with_an_unreadable_part(tmp_path: Path) -> None:
    home = tmp_path / "fakehome"
    folder = _make_cache(home, CacheKind.PIP)
    locked = folder / "locked"
    locked.mkdir()
    locked.chmod(0o000)
    try:
        found = _collect(home, tmp_path)
    finally:
        locked.chmod(0o700)

    assert found[CacheKind.PIP].size == _blocks(folder, folder / "data.bin", locked)
