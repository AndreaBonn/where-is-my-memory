import json
from dataclasses import replace
from datetime import UTC, timedelta, timezone
from pathlib import Path
from typing import Any, cast

import pytest

from tests.helpers import invalid_model_value
from wimm import model as m
from wimm.model import (
    SCHEMA_VERSION,
    ActivityAssessment,
    ActivityState,
    Category,
    ContainerMember,
    ProcessMember,
    Protection,
)
from wimm.serialize import SnapshotFormatError, snapshot_from_json, snapshot_to_json

FIXTURE = Path(__file__).parent / "fixtures" / "snapshot_whitebox.json"


@pytest.fixture
def document() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(FIXTURE.read_text()))


@pytest.fixture
def snapshot() -> m.Snapshot:
    return snapshot_from_json(text=FIXTURE.read_text())


def test_fixture_roundtrip_exact_json_values_and_model(
    snapshot: m.Snapshot, document: dict[str, Any]
) -> None:
    encoded = snapshot_to_json(snapshot=snapshot)
    assert json.loads(encoded) == document
    assert snapshot_from_json(text=encoded) == snapshot
    assert SCHEMA_VERSION == 3
    group = snapshot.groups[0]
    assert group.category is Category.PROJECT
    assert group.protection is Protection.ACTIONABLE
    assert isinstance(group.members[0], ContainerMember)
    assert isinstance(group.members[1], ProcessMember)
    assert group.members[1].create_time == 1760590000.12


@pytest.mark.parametrize(
    "indices,category",
    [
        ((0,), Category.CONTAINER),
        ((1,), Category.DEV_SERVER),
        ((0, 1), Category.PROJECT),
    ],
)
def test_member_union_variants_roundtrip(
    snapshot: m.Snapshot, indices: tuple[int, ...], category: Category
) -> None:
    group = snapshot.groups[0]
    group = replace(group, category=category, members=tuple(group.members[i] for i in indices))
    updated = replace(snapshot, groups=(group,))
    assert snapshot_from_json(text=snapshot_to_json(snapshot=updated)) == updated


def test_unknown_activity_nullable_fields_and_timezone_roundtrip(snapshot: m.Snapshot) -> None:
    unknown = ActivityAssessment(state=ActivityState.UNKNOWN, since=None, reason="In osservazione")
    group = replace(
        snapshot.groups[0],
        activity=unknown,
        primary_action=None,
        snoozed_until=snapshot.taken_at.astimezone(timezone(timedelta(hours=-7))),
    )
    member = group.members[1]
    assert isinstance(member, ProcessMember)
    process = replace(member, cwd=None, activity=unknown)
    updated = replace(
        snapshot,
        groups=(replace(group, members=(process,)),),
        taken_at=snapshot.taken_at.astimezone(UTC),
    )
    decoded = snapshot_from_json(text=snapshot_to_json(snapshot=updated))
    assert decoded == updated
    assert decoded.taken_at.utcoffset() == timedelta(0)
    snoozed_until = decoded.groups[0].snoozed_until
    assert snoozed_until is not None
    assert snoozed_until.utcoffset() == timedelta(hours=-7)


def test_group_compose_project_roundtrips_and_may_be_null(
    snapshot: m.Snapshot, document: dict[str, Any]
) -> None:
    assert snapshot.groups[0].compose_project == "whitebox"
    plain = replace(snapshot.groups[0], compose_project=None)

    decoded = snapshot_from_json(text=snapshot_to_json(snapshot=replace(snapshot, groups=(plain,))))

    assert decoded.groups[0].compose_project is None
    del document["groups"][0]["compose_project"]
    with pytest.raises(ValueError, match="compose_project"):
        snapshot_from_json(text=json.dumps(document))


def set_path(document: dict[str, Any], path: tuple[str | int, ...], value: object) -> None:
    target: Any = document
    for key in path[:-1]:
        target = (
            cast(dict[str, Any], target)[key]
            if isinstance(key, str)
            else cast(list[Any], target)[key]
        )
    key = path[-1]
    if isinstance(key, str):
        cast(dict[str, Any], target)[key] = value
    else:
        cast(list[Any], target)[key] = value


@pytest.mark.parametrize(
    "path,value",
    [
        (("schema",), 1),
        (("schema",), 2),
        (("schema",), 4),
        (("schema",), True),
        (("schema",), 1.0),
        (("pressure",), "bad"),
        (("pressure",), 1),
        (("taken_at",), "2026-10-16T10:30:00"),
        (("taken_at",), 123),
        (("groups",), {}),
        (("docker", "available"), 1),
        (("memory", "total"), 1.5),
        (("memory", "used"), -1),
        (("disk", "free"), True),
        (("groups", 0, "category"), "project"),
        (("groups", 0, "protection"), "bad"),
        (("groups", 0, "protection"), "protected"),
        (("groups", 0, "ignored"), "false"),
        (("groups", 0, "compose_project"), 1),
        (("groups", 0, "ports", 0), "8000"),
        (("groups", 0, "name"), None),
        (("groups", 0, "activity", "state"), "bad"),
        (("groups", 0, "activity", "since"), None),
        (("groups", 0, "primary_action", "risk"), "bad"),
        (("groups", 0, "primary_action", "risk"), 0),
        (("groups", 0, "primary_action", "kind"), "stop_group"),
        (("groups", 0, "members", 0, "kind"), "other"),
        (("groups", 0, "members", 1, "create_time"), True),
        (("groups", 0, "members", 1, "create_time"), "1760590000.12"),
        (("memory", "breakdown", "kernel_cache"), -1),
    ],
)
def test_decoder_rejects_bad_values_with_field_path(
    document: dict[str, Any], path: tuple[str | int, ...], value: object
) -> None:
    assert snapshot_from_json(text=json.dumps(document)).groups[0].name == "whitebox"
    set_path(document=document, path=path, value=value)
    with pytest.raises(ValueError, match=str(path[-1])):
        snapshot_from_json(text=json.dumps(document))


OBJECT_PATHS: list[tuple[str | int, ...]] = [
    (),
    ("memory",),
    ("memory", "breakdown"),
    ("disk",),
    ("reclaimable_now",),
    ("docker",),
    ("groups", 0),
    ("groups", 0, "activity"),
    ("groups", 0, "memory"),
    ("groups", 0, "primary_action"),
    ("groups", 0, "members", 0),
    ("groups", 0, "members", 1),
    ("groups", 0, "members", 0, "mounts", 0),
    ("protected_summary", 0),
]


@pytest.mark.parametrize("path", OBJECT_PATHS)
@pytest.mark.parametrize("operation", ["missing", "unknown", "wrong_type"])
def test_decoder_checks_object_fields_at_every_level(
    document: dict[str, Any], path: tuple[str | int, ...], operation: str
) -> None:
    assert snapshot_from_json(text=json.dumps(document)).pressure.value == "warning"
    target: Any = document
    for key in path:
        target = (
            cast(dict[str, Any], target)[key]
            if isinstance(key, str)
            else cast(list[Any], target)[key]
        )
    field = "kernel_cache" if path == ("memory", "breakdown") else next(iter(target))
    if operation == "missing":
        del target[field]
    elif operation == "unknown":
        target["unexpected"] = 1
        field = "unexpected"
    elif path:
        set_path(document=document, path=path, value=[])
        field = str(path[-1])
    else:
        document = invalid_model_value([])
        field = "snapshot"
    with pytest.raises(ValueError, match=field):
        snapshot_from_json(text=json.dumps(document))


@pytest.mark.parametrize("text", ["{", "null", "[]", "42", '{"schema":NaN}', '{"schema":Infinity}'])
def test_decoder_rejects_malformed_document(text: str) -> None:
    assert snapshot_from_json(text=FIXTURE.read_text()).groups[0].name == "whitebox"
    with pytest.raises(ValueError):
        snapshot_from_json(text=text)


def test_snapshot_invariants_and_protected_members(snapshot: m.Snapshot) -> None:
    assert snapshot.taken_at >= snapshot.monitor_started_at
    for changes, message in [
        ({"taken_at": snapshot.monitor_started_at - timedelta(seconds=1)}, "taken_at"),
        ({"groups": snapshot.groups * 2}, "groups"),
        ({"groups": list(snapshot.groups)}, "groups"),
    ]:
        with pytest.raises(ValueError, match=message):
            replace(snapshot, **invalid_model_value(changes))
    process = snapshot.groups[0].members[1]
    assert isinstance(process, ProcessMember)
    assert replace(process, actions=()).category is Category.DEV_SERVER
    with pytest.raises(ValueError, match="PROJECT"):
        replace(process, category=Category.PROJECT)
    for category in (Category.SYSTEM, Category.SESSION, Category.SELF):
        protected = replace(process, category=category, actions=())
        assert protected.protection is Protection.PROTECTED
        with pytest.raises(ValueError, match="protected"):
            replace(protected, actions=process.actions)
        group = replace(
            snapshot.groups[0], category=category, members=(protected,), primary_action=None
        )
        assert group.protection is Protection.PROTECTED
        with pytest.raises(ValueError, match="protected"):
            replace(group, primary_action=snapshot.groups[0].primary_action)
        with pytest.raises(ValueError, match="protected"):
            replace(group, members=(process,))


@pytest.mark.parametrize("value", ["SAFE", "Safe", float("nan"), float("inf"), 10**400])
def test_decoder_rejects_noncanonical_risk_and_nonfinite_creation_time(
    document: dict[str, Any], value: object
) -> None:
    process = snapshot_from_json(text=json.dumps(document)).groups[0].members[1]
    assert isinstance(process, ProcessMember)
    assert process.create_time == 1760590000.12
    field = "risk" if isinstance(value, str) else "create_time"
    path: tuple[str | int, ...] = (
        ("groups", 0, "primary_action", field)
        if field == "risk"
        else ("groups", 0, "members", 1, field)
    )
    set_path(document=document, path=path, value=value)
    with pytest.raises(ValueError, match=field):
        snapshot_from_json(text=json.dumps(document))


def test_breakdown_duplicate_categories_and_container_protection(snapshot: m.Snapshot) -> None:
    breakdown = snapshot.memory.breakdown
    assert breakdown.categories[0] == (Category.CONTAINER, 950000000)
    with pytest.raises(ValueError, match="categories"):
        replace(breakdown, categories=breakdown.categories * 2)
    assert snapshot.groups[0].members[0].protection is Protection.ACTIONABLE


@pytest.mark.parametrize(
    "section,fields",
    [
        ("memory", ("total", "available", "used", "swap_total", "swap_used")),
        ("disk", ("total", "used", "free")),
        ("reclaimable_now", ("ram", "disk")),
    ],
)
def test_model_snapshot_byte_fields_reject_negative_and_noninteger_values(
    snapshot: m.Snapshot, section: str, fields: tuple[str, ...]
) -> None:
    instance = getattr(snapshot, section)
    for field in fields:
        assert getattr(instance, field) >= 0
        for value in (-1, 1.5, True):
            with pytest.raises(ValueError, match=field):
                replace(instance, **invalid_model_value({field: value}))


def test_snapshot_auxiliary_byte_fields_reject_invalid_values(snapshot: m.Snapshot) -> None:
    breakdown = snapshot.memory.breakdown
    assert breakdown.kernel_cache == 6500000000
    for field in ("kernel_cache", "unattributed"):
        with pytest.raises(ValueError, match=field):
            replace(breakdown, **invalid_model_value({field: -1}))
    with pytest.raises(ValueError, match="categories"):
        replace(breakdown, categories=invalid_model_value(((Category.OTHER, 1.5),)))
    protected = snapshot.protected_summary[0]
    assert protected.memory == 1400000000
    with pytest.raises(ValueError, match="memory"):
        replace(protected, memory=invalid_model_value(True))


def test_process_risk_facts_roundtrip_and_are_required(document: dict[str, Any]) -> None:
    process = snapshot_from_json(text=FIXTURE.read_text()).groups[0].members[1]
    assert isinstance(process, ProcessMember)
    assert (process.uid, process.has_documents, process.is_foreground) == (1000, False, True)
    for field in ("uid", "has_documents", "is_foreground"):
        broken = json.loads(json.dumps(document))
        del broken["groups"][0]["members"][1][field]
        with pytest.raises(SnapshotFormatError, match=field):
            snapshot_from_json(text=json.dumps(broken))


@pytest.mark.parametrize(
    "field,value", [("uid", -1), ("uid", True), ("has_documents", 1), ("is_foreground", "yes")]
)
def test_process_risk_facts_reject_invalid_values(
    document: dict[str, Any], field: str, value: object
) -> None:
    document["groups"][0]["members"][1][field] = value

    with pytest.raises(SnapshotFormatError, match=field):
        snapshot_from_json(text=json.dumps(document))


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
