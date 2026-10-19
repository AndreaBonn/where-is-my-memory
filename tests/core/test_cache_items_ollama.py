import json

import pytest

from wimm.core.cache_items import TreeEntry, TreeListing, items_for
from wimm.model import CacheItemKind
from wimm.model.cache_items import CacheItem, CacheRest
from wimm.model.disk import CacheKind

from .cache_items_helpers import d, f

ROOT = "/home/u/.ollama/models"
SHARED = "a" * 64
GEMMA_TEMPLATE = "b" * 64
GEMMA_CONFIG = "c" * 64
OWN_LAYER = "d" * 64
OWN_CONFIG = "e" * 64
GEMMA = "manifests/registry.ollama.ai/library/gemma3/4b"
MINE = "manifests/registry.ollama.ai/someone/mymodel/latest"
BLOB_SIZES = {SHARED: 3000, GEMMA_TEMPLATE: 100, GEMMA_CONFIG: 10, OWN_LAYER: 200, OWN_CONFIG: 20}


def _manifest(*, layers: list[str], config: str) -> str:
    return json.dumps(
        {
            "schemaVersion": 2,
            "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
            "config": {"digest": f"sha256:{config}", "size": 489, "mediaType": "x"},
            "layers": [
                {"digest": f"sha256:{digest}", "size": 1, "mediaType": "x"} for digest in layers
            ],
        }
    )


def _blobs(sizes: dict[str, int]) -> list[TreeEntry]:
    return [d("blobs"), *(f(f"blobs/sha256-{digest}", size) for digest, size in sizes.items())]


def _tree(*, manifests: dict[str, str], sizes: dict[str, int] | None = None) -> TreeListing:
    entries = [d("manifests"), *(f(path, 400) for path in manifests)]
    entries += _blobs(BLOB_SIZES if sizes is None else sizes)
    return TreeListing(root=ROOT, entries=tuple(entries), texts=tuple(manifests.items()))


def _two_models() -> dict[str, str]:
    return {
        GEMMA: _manifest(layers=[SHARED, GEMMA_TEMPLATE], config=GEMMA_CONFIG),
        MINE: _manifest(layers=[SHARED, OWN_LAYER], config=OWN_CONFIG),
    }


def _split(listing: TreeListing, size: int = 10_000) -> tuple[tuple[CacheItem, ...], CacheRest]:
    return items_for(kind=CacheKind.OLLAMA, listing=listing, size=size)


def test_two_models_sharing_a_layer_split_it_into_the_rest() -> None:
    items, rest = _split(_tree(manifests=_two_models()))
    assert {item.id: item.size for item in items} == {
        "gemma3:4b": 110,
        "someone/mymodel:latest": 220,
    }
    assert rest.shared == 3000
    assert rest.unattributed == 10_000 - 110 - 220 - 3000


def test_a_layer_used_by_three_models_is_counted_once_in_shared() -> None:
    manifests = {
        **_two_models(),
        "manifests/registry.ollama.ai/library/x/1": _manifest(layers=[SHARED], config="9" * 64),
    }
    items, rest = _split(_tree(manifests=manifests))
    assert rest.shared == 3000
    assert {item.id: item.size for item in items}["someone/mymodel:latest"] == 220
    assert {item.id: item.size for item in items}["x:1"] == 0


def test_item_carries_kind_manifest_path_and_manifest_identity() -> None:
    listing = _tree(manifests=_two_models())
    items, _ = _split(listing)
    item = next(i for i in items if i.id == "gemma3:4b")
    manifest = next(e for e in listing.entries if e.path == GEMMA)
    assert item.kind is CacheItemKind.OLLAMA_MODEL
    assert item.path == f"{ROOT}/{GEMMA}"
    assert (item.st_ino, item.st_dev) == (manifest.st_ino, manifest.st_dev)
    assert item.title == item.id


@pytest.mark.parametrize(
    ("manifest_path", "expected"),
    [
        ("manifests/registry.ollama.ai/library/llama3/8b", "llama3:8b"),
        ("manifests/registry.ollama.ai/someone/llama3/8b", "someone/llama3:8b"),
        ("manifests/hf.co/org/repo/Q4_K_M", "hf.co/org/repo:Q4_K_M"),
        ("manifests/example.com/library/llama3/8b", "example.com/library/llama3:8b"),
    ],
)
def test_title_is_the_name_ollama_rm_takes(manifest_path: str, expected: str) -> None:
    manifests = {manifest_path: _manifest(layers=[SHARED], config=GEMMA_CONFIG)}
    items, _ = _split(_tree(manifests=manifests))
    assert [i.id for i in items] == [expected]


def test_a_digest_whose_blob_is_missing_contributes_nothing() -> None:
    sizes = {k: v for k, v in BLOB_SIZES.items() if k != GEMMA_TEMPLATE}
    items, _ = _split(_tree(manifests=_two_models(), sizes=sizes))
    assert {i.id: i.size for i in items}["gemma3:4b"] == 10


def test_a_digest_repeated_inside_one_manifest_is_counted_once() -> None:
    manifests = {GEMMA: _manifest(layers=[GEMMA_TEMPLATE, GEMMA_TEMPLATE], config=GEMMA_CONFIG)}
    items, _ = _split(_tree(manifests=manifests))
    assert [i.size for i in items] == [110]


@pytest.mark.parametrize(
    "digest",
    [
        "sha256:" + "A" * 64,
        "sha256:" + "a" * 63,
        "sha512:" + "a" * 64,
        "sha256:../" + "a" * 61,
        "",
        "a" * 64,
    ],
)
def test_a_malformed_digest_drops_that_model_only(digest: str) -> None:
    broken = json.loads(_manifest(layers=[OWN_LAYER], config=OWN_CONFIG))
    broken["layers"].append({"digest": digest, "size": 1, "mediaType": "x"})
    manifests = {**_two_models(), MINE: json.dumps(broken)}
    items, rest = _split(_tree(manifests=manifests))
    assert [i.id for i in items] == ["gemma3:4b"]
    assert rest.shared == 0


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not json",
        "[]",
        "{}",
        '{"config": {}, "layers": []}',
        '{"config": {"digest": 1}, "layers": []}',
        '{"config": {"digest": "sha256:' + "c" * 64 + '"}, "layers": {}}',
        '{"config": {"digest": "sha256:' + "c" * 64 + '"}, "layers": [1]}',
    ],
)
def test_an_unreadable_manifest_is_not_an_item(text: str) -> None:
    manifests = {**_two_models(), MINE: text}
    items, _ = _split(_tree(manifests=manifests))
    assert [i.id for i in items] == ["gemma3:4b"]


def test_a_text_that_is_not_a_five_level_manifest_file_is_ignored() -> None:
    listing = _tree(manifests=_two_models())
    extra = (
        (
            "manifests/registry.ollama.ai/library/gemma3",
            _manifest(layers=[SHARED], config=OWN_CONFIG),
        ),
        (
            "manifests/registry.ollama.ai/library/a/b/c",
            _manifest(layers=[SHARED], config=OWN_CONFIG),
        ),
        ("blobs/sha256-" + SHARED, _manifest(layers=[SHARED], config=OWN_CONFIG)),
        ("manifests/h/n/m/ghost", _manifest(layers=[SHARED], config=OWN_CONFIG)),
    )
    noisy = TreeListing(root=ROOT, entries=listing.entries, texts=(*listing.texts, *extra))
    items, _ = _split(noisy)
    assert sorted(i.id for i in items) == ["gemma3:4b", "someone/mymodel:latest"]


def test_without_manifest_texts_the_cache_has_no_items() -> None:
    listing = _tree(manifests=_two_models())
    bare = TreeListing(root=ROOT, entries=listing.entries)
    items, rest = _split(bare)
    assert items == ()
    assert (rest.shared, rest.unattributed) == (0, 10_000)


def test_unreferenced_blobs_and_unreadable_manifests_stay_unattributed() -> None:
    manifests = {**_two_models(), "manifests/h/n/m/bad": "nope"}
    items, rest = _split(_tree(manifests=manifests, sizes={**BLOB_SIZES, "f" * 64: 500}))
    assert sum(i.size for i in items) + rest.shared == 110 + 220 + 3000
    assert rest.unattributed == 10_000 - 110 - 220 - 3000
