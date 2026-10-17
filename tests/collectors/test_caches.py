import os
from pathlib import Path

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


def _collect(home: Path, tmp_path: Path) -> dict[CacheKind, CacheEntry]:
    entries = collect_caches(home=home, cache_dir=tmp_path / "sizes", sleep=lambda _s: None)
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
