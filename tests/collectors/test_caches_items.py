import os
from pathlib import Path

import pytest

from wimm.collectors import caches
from wimm.collectors.cache_table import read_cache_table
from wimm.collectors.caches import collect_caches
from wimm.collectors.dirsize import measure_dir_size
from wimm.model.disk import CacheEntry, CacheKind


def _hf_root(home: Path) -> Path:
    root = home / ".cache" / "huggingface" / "hub"
    (root / ".locks").mkdir(parents=True)
    return root


def _blob(path: Path, payload: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"b" * payload)
    return path


def _model(root: Path, name: str, own: int) -> None:
    repo = root / f"models--{name}"
    _blob(repo / "blobs" / "own", own)
    (repo / "snapshots" / "rev").mkdir(parents=True)
    (repo / "snapshots" / "rev" / "w.bin").symlink_to("../../blobs/own")


def _collect(home: Path, tmp_path: Path) -> dict[CacheKind, CacheEntry]:
    table = read_cache_table(environ={}, home=home, roots=())
    found = collect_caches(table=table, cache_dir=tmp_path / "sizes", sleep=lambda _s: None)
    return {entry.kind: entry for entry in found}


def _size(path: Path) -> int:
    return os.lstat(path).st_blocks * 512


def test_collect_caches_attaches_hf_items_shared_and_rest(tmp_path: Path) -> None:
    home = tmp_path / "home"
    root = _hf_root(home)
    _model(root, "org--a", own=8192)
    _model(root, "org--b", own=4096)
    shared = _blob(root / "blobs" / "ab" / "sha", 12288)
    for name in ("org--a", "org--b"):
        link = root / f"models--{name}" / "snapshots" / "rev" / "shared.bin"
        link.symlink_to(os.path.relpath(shared, link.parent))
    entry = _collect(home, tmp_path)[CacheKind.HUGGINGFACE]
    sizes = {item.title: item.size for item in entry.items}
    assert sizes == {
        "org/a": _size(root / "models--org--a" / "blobs" / "own"),
        "org/b": _size(root / "models--org--b" / "blobs" / "own"),
    }
    assert entry.rest.shared == _size(shared)
    accounted = sum(sizes.values()) + entry.rest.shared + entry.rest.unattributed
    assert accounted == entry.size


def test_collect_caches_never_counts_a_link_leaving_the_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    root = _hf_root(home)
    _model(root, "org--a", own=4096)
    outside = _blob(tmp_path / "elsewhere" / "big.bin", 65536)
    (root / "models--org--a" / "snapshots" / "rev" / "out.bin").symlink_to(outside)
    real = os.path.realpath
    seen: list[str] = []

    def spy(path: str, *, strict: bool = False) -> str:
        seen.append(str(path))
        return real(path, strict=strict)

    monkeypatch.setattr(os.path, "realpath", spy)
    entry = _collect(home, tmp_path)[CacheKind.HUGGINGFACE]
    (item,) = entry.items
    assert item.size == _size(root / "models--org--a" / "blobs" / "own")
    assert entry.rest.shared == 0
    assert all("snapshots" not in path and "elsewhere" not in path for path in seen)


def test_collect_caches_counts_hard_linked_blob_once(tmp_path: Path) -> None:
    home = tmp_path / "home"
    root = _hf_root(home)
    repo = root / "models--org--a"
    _blob(repo / "blobs" / "one", 8192)
    os.link(repo / "blobs" / "one", repo / "blobs" / "two")
    (repo / "snapshots" / "rev").mkdir(parents=True)
    (repo / "snapshots" / "rev" / "x").symlink_to("../../blobs/one")
    (repo / "snapshots" / "rev" / "y").symlink_to("../../blobs/two")
    entry = _collect(home, tmp_path)[CacheKind.HUGGINGFACE]
    (item,) = entry.items
    assert item.size == _size(repo / "blobs" / "one")


def test_collect_caches_does_not_walk_kinds_without_a_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    folder = home / ".cache" / "uv"
    _blob(folder / "data.bin", 5000)

    def boom(**kwargs: object) -> None:
        raise AssertionError("walker must not run for a kind without rule")

    monkeypatch.setattr(caches, "list_tree", boom)
    entry = _collect(home, tmp_path)[CacheKind.UV]
    assert entry.items == ()
    assert entry.rest.shared == 0
    assert entry.rest.unattributed == 0


def test_collect_caches_fails_closed_when_items_exceed_measured_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    home = tmp_path / "home"
    root = _hf_root(home)
    _model(root, "org--a", own=16384)
    real = measure_dir_size
    small = real(root=root, cache_dir=tmp_path / "sizes", sleep=lambda _s: None)
    stale = type(small)(size_bytes=4096, error_count=0, from_cache=True)
    monkeypatch.setattr(caches, "measure_dir_size", lambda **kwargs: stale)
    with caplog.at_level("WARNING"):
        entry = _collect(home, tmp_path)[CacheKind.HUGGINGFACE]
    assert entry.size == 4096
    assert entry.items == ()
    assert entry.rest.shared == 0
    assert entry.rest.unattributed == 0
    assert any("exceed" in record.message for record in caplog.records)
