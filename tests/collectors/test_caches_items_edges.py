import os
from pathlib import Path

from wimm.collectors.cache_table import read_cache_table
from wimm.collectors.caches import collect_caches
from wimm.model.disk import CacheEntry, CacheKind


def _hf_root(home: Path) -> Path:
    root = home / ".cache" / "huggingface" / "hub"
    (root / ".locks").mkdir(parents=True)
    return root


def _blob(path: Path, payload: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"b" * payload)
    return path


def _hf(home: Path, tmp_path: Path) -> CacheEntry:
    table = read_cache_table(environ={}, home=home, roots=())
    found = collect_caches(table=table, cache_dir=tmp_path / "sizes", sleep=lambda _s: None)
    return {entry.kind: entry for entry in found}[CacheKind.HUGGINGFACE]


def _size(path: Path) -> int:
    return os.lstat(path).st_blocks * 512


def test_collect_caches_survives_a_blank_repo_folder_next_to_a_valid_one(tmp_path: Path) -> None:
    home = tmp_path / "home"
    root = _hf_root(home)
    _blob(root / "models-- " / "blobs" / "junk", 4096)
    valid = _blob(root / "models--org--a" / "blobs" / "own", 8192)
    entry = _hf(home, tmp_path)
    assert [item.title for item in entry.items] == ["org/a"]
    assert entry.items[0].size == _size(valid)
    assert entry.rest.unattributed >= _size(root / "models-- " / "blobs" / "junk")


def test_collect_caches_puts_a_cross_repo_hard_link_in_shared(tmp_path: Path) -> None:
    home = tmp_path / "home"
    root = _hf_root(home)
    one = _blob(root / "models--o--a" / "blobs" / "x", 8192)
    (root / "models--o--b" / "blobs").mkdir(parents=True)
    os.link(one, root / "models--o--b" / "blobs" / "x")
    entry = _hf(home, tmp_path)
    assert {item.title: item.size for item in entry.items} == {"o/a": 0, "o/b": 0}
    assert entry.rest.shared == _size(one)
