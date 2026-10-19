import json
from typing import Any

import pytest

from wimm.core.disk_wire import disk_report_from_json, disk_report_to_json
from wimm.model import CacheEntry, CacheItem, CacheItemKind, CacheKind, CacheRest
from wimm.wire_decoders import SnapshotFormatError

from .disk_helpers import FIXTURES, MB, cache, report

SAMPLE = FIXTURES / "disk_report_sample.json"


def _item(*, id: str, size: int, kind: CacheItemKind) -> CacheItem:
    return CacheItem(
        id=id,
        title=id.split("--", 1)[-1].replace("--", "/"),
        path=f"/home/u/.cache/huggingface/hub/{id}",
        size=size,
        st_ino=40,
        st_dev=2049,
        kind=kind,
    )


def _hf_entry() -> CacheEntry:
    return CacheEntry(
        kind=CacheKind.HUGGINGFACE,
        path="/home/u/.cache/huggingface",
        size=10 * MB,
        st_ino=11,
        st_dev=2049,
        items=(
            _item(id="models--org--a", size=4 * MB, kind=CacheItemKind.HF_MODEL),
            _item(id="datasets--org--b", size=3 * MB, kind=CacheItemKind.HF_DATASET),
        ),
        rest=CacheRest(shared=2 * MB, unattributed=MB),
    )


def test_cache_with_two_items_and_a_rest_survives_a_roundtrip() -> None:
    built = report(caches=(_hf_entry(),))

    text = disk_report_to_json(report=built)
    wire = json.loads(text)["caches"][0]

    assert disk_report_from_json(text=text) == built
    assert [i["kind"] for i in wire["items"]] == ["hf_model", "hf_dataset"]
    assert wire["rest"] == {"shared": 2 * MB, "unattributed": MB}


def test_cache_without_items_keeps_the_old_json_shape() -> None:
    built = report(caches=(cache(kind=CacheKind.UV),))

    wire = json.loads(disk_report_to_json(report=built))["caches"][0]

    assert set(wire) == {"kind", "path", "size", "st_ino", "st_dev"}


def test_cache_with_only_a_rest_encodes_the_rest_and_no_items() -> None:
    entry = CacheEntry(
        kind=CacheKind.HUGGINGFACE,
        path="/p",
        size=MB,
        st_ino=1,
        st_dev=2,
        rest=CacheRest(unattributed=MB),
    )

    wire = json.loads(disk_report_to_json(report=report(caches=(entry,))))["caches"][0]

    assert "items" not in wire
    assert wire["rest"] == {"shared": 0, "unattributed": MB}


def test_schema_four_report_is_rejected() -> None:
    document: dict[str, Any] = json.loads(SAMPLE.read_text(encoding="utf-8"))
    document["schema"] = 4

    with pytest.raises(SnapshotFormatError, match="schema"):
        disk_report_from_json(text=json.dumps(document))


@pytest.mark.parametrize(
    "mutate,message",
    [
        (lambda c: c["items"][0].update(extra=1), "extra"),
        (lambda c: c["items"][0].update(kind="hf_other"), "CacheItemKind"),
        (lambda c: c["items"][1].update(id=c["items"][0]["id"]), "unique"),
        (lambda c: c["rest"].update(shared=-1), "shared"),
        (lambda c: c["rest"].pop("unattributed"), "unattributed"),
        (lambda c: c.update(items=[]), "exceed"),
    ],
)
def test_invalid_items_or_rest_are_rejected(mutate: Any, message: str) -> None:
    document = json.loads(disk_report_to_json(report=report(caches=(_hf_entry(),))))
    cache_doc = document["caches"][0]
    if message == "exceed":
        cache_doc["size"] = MB
    mutate(cache_doc)

    with pytest.raises(SnapshotFormatError, match=message):
        disk_report_from_json(text=json.dumps(document))
