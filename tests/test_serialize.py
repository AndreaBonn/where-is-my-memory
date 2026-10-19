import json
from dataclasses import replace
from datetime import UTC, timedelta, timezone
from typing import Any, cast

import pytest

from tests.serialize_helpers import FIXTURE
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
from wimm.serialize import snapshot_from_json, snapshot_to_json


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
    assert SCHEMA_VERSION == 4
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
