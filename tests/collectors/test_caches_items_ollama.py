import json
from pathlib import Path

from wimm.collectors.cache_table import read_cache_table
from wimm.collectors.caches import collect_caches
from wimm.model.disk import CacheEntry, CacheKind

SHARED = "a" * 64
OWN = "b" * 64
CONFIG = "c" * 64


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _manifest(*, layer: str, config: str) -> bytes:
    body = {
        "config": {"digest": f"sha256:{config}"},
        "layers": [{"digest": f"sha256:{SHARED}"}, {"digest": f"sha256:{layer}"}],
    }
    return json.dumps(body).encode()


def _collect(home: Path, tmp_path: Path, environ: dict[str, str]) -> CacheEntry:
    table = read_cache_table(environ=environ, home=home, roots=())
    found = collect_caches(table=table, cache_dir=tmp_path / "sizes", sleep=lambda _s: None)
    return next(entry for entry in found if entry.kind is CacheKind.OLLAMA)


def _store(root: Path) -> None:
    registry = root / "manifests" / "registry.ollama.ai" / "library"
    _write(registry / "gemma3" / "4b", _manifest(layer=OWN, config=CONFIG))
    _write(registry / "other" / "1", _manifest(layer="d" * 64, config="e" * 64))
    _write(root / "blobs" / f"sha256-{SHARED}", b"s" * 20000)
    _write(root / "blobs" / f"sha256-{OWN}", b"o" * 9000)
    _write(root / "blobs" / f"sha256-{CONFIG}", b"c" * 500)
    _write(root / "blobs" / f"sha256-{'d' * 64}", b"d" * 3000)


def test_collect_caches_splits_the_home_ollama_store_into_models(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _store(home / ".ollama" / "models")
    entry = _collect(home, tmp_path, {})
    assert {item.id for item in entry.items} == {"gemma3:4b", "other:1"}
    sizes = {item.id: item.size for item in entry.items}
    assert sizes["gemma3:4b"] > sizes["other:1"] > 0
    assert entry.rest.shared > 0
    accounted = sum(sizes.values()) + entry.rest.shared + entry.rest.unattributed
    assert accounted == entry.size


def test_collect_caches_follows_ollama_models_for_the_manifest_items(tmp_path: Path) -> None:
    store = tmp_path / "home" / "data" / "models"
    _store(store)
    entry = _collect(tmp_path / "home", tmp_path, {"OLLAMA_MODELS": str(store)})
    assert {item.id for item in entry.items} == {"gemma3:4b", "other:1"}


def test_collect_caches_keeps_an_ollama_store_without_manifests_whole(tmp_path: Path) -> None:
    root = tmp_path / "home" / ".ollama" / "models"
    _write(root / "manifests" / "registry.ollama.ai" / "x", b"{}")
    _write(root / "blobs" / f"sha256-{SHARED}", b"s" * 5000)
    entry = _collect(tmp_path / "home", tmp_path, {})
    assert entry.items == ()
    assert entry.size > 0
