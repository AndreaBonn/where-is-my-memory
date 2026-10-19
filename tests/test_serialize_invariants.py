import json
from dataclasses import replace
from datetime import timedelta
from typing import Any, cast

import pytest

from tests.helpers import invalid_model_value
from tests.serialize_helpers import FIXTURE, set_path
from wimm import model as m
from wimm.model import (
    Category,
    ProcessMember,
    Protection,
)
from wimm.serialize import SnapshotFormatError, snapshot_from_json


@pytest.fixture
def document() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(FIXTURE.read_text()))


@pytest.fixture
def snapshot() -> m.Snapshot:
    return snapshot_from_json(text=FIXTURE.read_text())


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
