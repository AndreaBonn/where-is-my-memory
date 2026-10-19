"""T-6.37a: `model_id` is an optional wire field, so the schema stays at 5."""

import json
from typing import Any

import pytest

from wimm.core.disk_wire import disk_report_from_json, disk_report_to_json
from wimm.model import SCHEMA_VERSION, CacheEntry, CacheItem, CacheItemKind, CacheKind
from wimm.wire_decoders import SnapshotFormatError

from .disk_helpers import report
from .ollama_system_helpers import MB, MODEL_ID, SYSTEM_PATH, model, system_entry


def _wire_of(*, entry: CacheEntry) -> dict[str, Any]:
    document = json.loads(disk_report_to_json(report=report(caches=(entry,))))
    return dict(document["caches"][0])


def _hf_entry() -> CacheEntry:
    item = CacheItem(
        id="models--org--a",
        title="org/a",
        path="/home/u/.cache/huggingface/hub/models--org--a",
        size=MB,
        st_ino=5,
        st_dev=2049,
        kind=CacheItemKind.HF_MODEL,
    )
    return CacheEntry(
        kind=CacheKind.HUGGINGFACE,
        path="/home/u/.cache/huggingface",
        size=MB,
        st_ino=11,
        st_dev=2049,
        items=(item,),
    )


def test_system_entry_roundtrips_with_its_model_ids() -> None:
    built = report(caches=(system_entry(),))

    text = disk_report_to_json(report=built)
    wire = json.loads(text)["caches"][0]

    assert disk_report_from_json(text=text) == built
    assert wire["kind"] == "ollama_system"
    assert wire["path"] == SYSTEM_PATH
    assert wire["items"][0]["model_id"] == MODEL_ID


def test_an_item_without_model_id_keeps_the_old_json_shape() -> None:
    old = _wire_of(entry=_hf_entry())["items"][0]
    named = _wire_of(entry=system_entry())["items"][0]

    assert "model_id" not in old
    assert named["model_id"] == MODEL_ID


def test_an_item_written_without_model_id_decodes_to_empty() -> None:
    built = report(caches=(_hf_entry(),))

    decoded = disk_report_from_json(text=disk_report_to_json(report=built))

    assert decoded.caches[0].items[0].model_id == ""


def test_schema_version_is_still_five() -> None:
    document = json.loads(disk_report_to_json(report=report(caches=(system_entry(),))))

    assert SCHEMA_VERSION == document["schema"] == 5


def test_a_wire_system_item_without_model_id_is_rejected() -> None:
    document = json.loads(disk_report_to_json(report=report(caches=(system_entry(),))))
    del document["caches"][0]["items"][0]["model_id"]

    with pytest.raises(SnapshotFormatError, match="model_id"):
        disk_report_from_json(text=json.dumps(document))


def test_a_malformed_model_id_on_the_wire_is_rejected() -> None:
    entry = system_entry(items=(model(), model(name="b:1")), size=2 * MB)
    document = json.loads(disk_report_to_json(report=report(caches=(entry,))))
    document["caches"][0]["items"][1]["model_id"] = "XYZ"

    with pytest.raises(SnapshotFormatError, match="model_id"):
        disk_report_from_json(text=json.dumps(document))
