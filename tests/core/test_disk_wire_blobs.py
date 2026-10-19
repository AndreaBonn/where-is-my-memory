import json

from wimm.core.disk_wire import disk_report_from_json, disk_report_to_json
from wimm.model import CacheEntry, CacheItem, CacheItemKind, CacheKind, ItemBlob

from .disk_helpers import report


def _entry(*, blobs: tuple[ItemBlob, ...]) -> CacheEntry:
    item = CacheItem(
        id="models--org--a",
        title="org/a",
        path="/home/u/.cache/huggingface/hub/models--org--a",
        size=2000,
        st_ino=5,
        st_dev=2049,
        kind=CacheItemKind.HF_MODEL,
        blobs=blobs,
    )
    return CacheEntry(
        kind=CacheKind.HUGGINGFACE,
        path="/home/u/.cache/huggingface",
        size=2000,
        st_ino=11,
        st_dev=2049,
        items=(item,),
    )


def test_blobs_survive_a_roundtrip() -> None:
    blob = ItemBlob(path="hub/blobs/3b/excl", size=2000, st_ino=7, st_dev=2049)
    built = report(caches=(_entry(blobs=(blob,)),))
    text = disk_report_to_json(report=built)
    assert json.loads(text)["caches"][0]["items"][0]["blobs"] == [
        {"path": "hub/blobs/3b/excl", "size": 2000, "st_ino": 7, "st_dev": 2049}
    ]
    assert disk_report_from_json(text=text) == built


def test_empty_blobs_are_left_out_and_read_back_as_empty() -> None:
    built = report(caches=(_entry(blobs=()),))
    text = disk_report_to_json(report=built)
    assert "blobs" not in json.loads(text)["caches"][0]["items"][0]
    assert disk_report_from_json(text=text) == built
