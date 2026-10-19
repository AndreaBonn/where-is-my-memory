import json
from dataclasses import replace
from typing import Any, cast

import pytest

from tests.serialize_helpers import FIXTURE
from wimm import model as m
from wimm.serialize import SnapshotFormatError, snapshot_from_json, snapshot_to_json


@pytest.fixture
def document() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(FIXTURE.read_text()))


@pytest.fixture
def snapshot() -> m.Snapshot:
    return snapshot_from_json(text=FIXTURE.read_text())


BREAKDOWN_VOICES = ("shared_tmpfs", "kernel_unreclaimable", "zram", "zswap")


def test_roundtrip_keeps_every_breakdown_voice(snapshot: m.Snapshot) -> None:
    breakdown = replace(
        snapshot.memory.breakdown, shared_tmpfs=11, kernel_unreclaimable=22, zram=33, zswap=44
    )
    updated = replace(snapshot, memory=replace(snapshot.memory, breakdown=breakdown))

    encoded = json.loads(snapshot_to_json(snapshot=updated))

    assert {name: encoded["memory"]["breakdown"][name] for name in BREAKDOWN_VOICES} == {
        "shared_tmpfs": 11,
        "kernel_unreclaimable": 22,
        "zram": 33,
        "zswap": 44,
    }
    assert snapshot_from_json(text=json.dumps(encoded)).memory.breakdown == breakdown


def test_zero_breakdown_voices_are_always_written(snapshot: m.Snapshot) -> None:
    zero = replace(
        snapshot.memory.breakdown, shared_tmpfs=0, kernel_unreclaimable=0, zram=0, zswap=0
    )
    updated = replace(snapshot, memory=replace(snapshot.memory, breakdown=zero))

    written = json.loads(snapshot_to_json(snapshot=updated))["memory"]["breakdown"]

    assert all(written[name] == 0 for name in BREAKDOWN_VOICES)


@pytest.mark.parametrize("voice", BREAKDOWN_VOICES)
def test_breakdown_missing_voice_is_rejected(document: dict[str, Any], voice: str) -> None:
    del document["memory"]["breakdown"][voice]

    with pytest.raises(SnapshotFormatError, match=voice):
        snapshot_from_json(text=json.dumps(document))


def test_schema_three_snapshot_is_rejected(document: dict[str, Any]) -> None:
    document["schema"] = 3

    with pytest.raises(SnapshotFormatError, match="schema"):
        snapshot_from_json(text=json.dumps(document))


def test_schema_two_snapshot_is_rejected(document: dict[str, Any]) -> None:
    document["schema"] = 2

    with pytest.raises(SnapshotFormatError, match="schema"):
        snapshot_from_json(text=json.dumps(document))


def test_video_memory_roundtrips_two_gpus_outside_the_breakdown(
    snapshot: m.Snapshot, document: dict[str, Any]
) -> None:
    assert snapshot.memory.video == (
        m.GpuMemory(vendor=m.GpuVendor.NVIDIA, used_bytes=2147483648, total_bytes=8589934592),
        m.GpuMemory(vendor=m.GpuVendor.AMD, used_bytes=536870912, total_bytes=4294967296),
    )
    encoded = json.loads(snapshot_to_json(snapshot=snapshot))
    assert encoded["memory"]["video"] == document["memory"]["video"]
    assert "video" not in encoded["memory"]["breakdown"]
    assert snapshot_from_json(text=json.dumps(encoded)) == snapshot


def test_no_gpu_means_empty_video_list(snapshot: m.Snapshot) -> None:
    bare = replace(snapshot, memory=replace(snapshot.memory, video=()))

    assert snapshot.memory.video != ()
    assert json.loads(snapshot_to_json(snapshot=bare))["memory"]["video"] == []
    assert snapshot_from_json(text=snapshot_to_json(snapshot=bare)).memory.video == ()


def test_video_field_is_required(document: dict[str, Any]) -> None:
    del document["memory"]["video"]

    with pytest.raises(SnapshotFormatError, match="video"):
        snapshot_from_json(text=json.dumps(document))


@pytest.mark.parametrize(
    "field,value",
    [
        ("vendor", "intel"),
        ("vendor", 1),
        ("used_bytes", -1),
        ("total_bytes", -1),
        ("used_bytes", 1.5),
        ("extra", 1),
    ],
)
def test_video_entry_rejects_invalid_values(
    document: dict[str, Any], field: str, value: object
) -> None:
    document["memory"]["video"][0][field] = value

    with pytest.raises(SnapshotFormatError, match=field):
        snapshot_from_json(text=json.dumps(document))


def test_video_model_rejects_negative_bytes() -> None:
    with pytest.raises(ValueError, match="used_bytes"):
        m.GpuMemory(vendor=m.GpuVendor.AMD, used_bytes=-1, total_bytes=10)
    with pytest.raises(ValueError, match="total_bytes"):
        m.GpuMemory(vendor=m.GpuVendor.AMD, used_bytes=0, total_bytes=-1)


def test_growth_roundtrips_as_an_object_and_as_null(
    snapshot: m.Snapshot, document: dict[str, Any]
) -> None:
    assert snapshot.groups[0].growth == m.GroupGrowth(delta_bytes=620_000_000, span_s=7200)
    encoded = json.loads(snapshot_to_json(snapshot=snapshot))
    assert encoded["groups"][0]["growth"] == {"delta_bytes": 620_000_000, "span_s": 7200}

    flat = replace(snapshot, groups=(replace(snapshot.groups[0], growth=None),))
    flat_json = json.loads(snapshot_to_json(snapshot=flat))
    assert flat_json["groups"][0]["growth"] is None
    assert snapshot_from_json(text=json.dumps(flat_json)) == flat


def test_growth_field_is_required_even_when_null(document: dict[str, Any]) -> None:
    del document["groups"][0]["growth"]

    with pytest.raises(SnapshotFormatError, match="growth"):
        snapshot_from_json(text=json.dumps(document))


@pytest.mark.parametrize(
    "field,value",
    [
        ("delta_bytes", 0),
        ("delta_bytes", -5),
        ("delta_bytes", 1.5),
        ("delta_bytes", True),
        ("span_s", 0),
        ("span_s", -1),
        ("span_s", "7200"),
        ("span_s", True),
        ("extra", 1),
    ],
)
def test_growth_entry_rejects_invalid_values(
    document: dict[str, Any], field: str, value: object
) -> None:
    document["groups"][0]["growth"][field] = value

    with pytest.raises(SnapshotFormatError, match=field):
        snapshot_from_json(text=json.dumps(document))


def test_growth_model_rejects_non_positive_values() -> None:
    with pytest.raises(ValueError, match="delta_bytes"):
        m.GroupGrowth(delta_bytes=0, span_s=60)
    with pytest.raises(ValueError, match="span_s"):
        m.GroupGrowth(delta_bytes=1, span_s=0)
