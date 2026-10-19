from dataclasses import replace
from datetime import datetime

import pytest

from tests.ui.viewmodel_helpers import FIXTURE, make_group, titles, with_groups
from wimm.model.enums import ActivityState, Category, Risk
from wimm.model.snapshot import (
    ProcessMember,
    Snapshot,
)
from wimm.serialize import snapshot_from_json


@pytest.fixture
def snapshot() -> Snapshot:
    return snapshot_from_json(text=FIXTURE.read_text())


@pytest.fixture
def now(snapshot: Snapshot) -> datetime:
    return snapshot.taken_at


def test_filter_only_idle_keeps_idle_groups(snapshot: Snapshot, now: datetime) -> None:
    groups = (
        make_group("idle", state=ActivityState.IDLE),
        make_group("busy", state=ActivityState.ACTIVE),
        make_group("unk", state=ActivityState.UNKNOWN, since=None),
    )
    shot = with_groups(snapshot, *groups)
    assert titles(shot, now, only_idle=True) == ["idle"]
    assert sorted(titles(shot, now)) == ["busy", "idle", "unk"]


def test_filter_by_category_set(snapshot: Snapshot, now: datetime) -> None:
    groups = (
        make_group("web", category=Category.BROWSER),
        make_group("srv", category=Category.DEV_SERVER),
        make_group("ai", category=Category.AI_CLI),
    )
    shot = with_groups(snapshot, *groups)
    chosen = frozenset({Category.BROWSER, Category.AI_CLI})
    assert sorted(titles(shot, now, categories=chosen)) == ["ai", "web"]


def test_filter_by_risk_set_excludes_rows_without_a_risk(snapshot: Snapshot, now: datetime) -> None:
    groups = (
        make_group("safe", risk=Risk.SAFE),
        make_group("care", risk=Risk.CAUTION),
        make_group("none", risk=None),
    )
    shot = with_groups(snapshot, *groups)
    assert titles(shot, now, risks=frozenset({Risk.CAUTION})) == ["care"]
    assert sorted(titles(shot, now, risks=frozenset({Risk.SAFE, Risk.CAUTION}))) == [
        "care",
        "safe",
    ]
    assert "none" in titles(shot, now)


def test_search_is_case_insensitive_on_name_and_explanation(
    snapshot: Snapshot, now: datetime
) -> None:
    groups = (
        make_group("Frontend"),
        make_group("other", explanation="lanciato dal TERMINALE"),
        make_group("noise"),
    )
    shot = with_groups(snapshot, *groups)
    assert titles(shot, now, query="frontEND") == ["Frontend"]
    assert titles(shot, now, query="terminale") == ["other"]
    assert titles(shot, now, query="  frontend  ") == ["Frontend"]


def test_search_matches_member_command_and_ports(snapshot: Snapshot, now: datetime) -> None:
    shot = with_groups(snapshot, make_group("noise"), *snapshot.groups)
    assert titles(shot, now, query="UVICORN app:main") == ["whitebox"]
    assert titles(shot, now, query="8000") == ["whitebox"]
    assert titles(shot, now, query="8080") == ["whitebox"]
    assert titles(shot, now, query="9999") == []


def test_search_matches_group_ports(snapshot: Snapshot, now: datetime) -> None:
    shot = with_groups(snapshot, make_group("srv", ports=(4321,)), make_group("noise"))
    assert titles(shot, now, query="4321") == ["srv"]


def test_search_is_accent_insensitive(snapshot: Snapshot, now: datetime) -> None:
    shot = with_groups(snapshot, make_group("noise"), make_group("x", explanation="attività"))
    assert titles(shot, now, query="attivita") == ["x"]
    assert titles(shot, now, query="ATTIVITÀ") == ["x"]
    assert titles(shot, now, query="attivite") == []


def test_search_matches_container_name_image_and_process_name(
    snapshot: Snapshot, now: datetime
) -> None:
    shot = with_groups(snapshot, make_group("noise"), *snapshot.groups)
    assert titles(shot, now, query="keycloak:26") == ["whitebox"]
    assert titles(shot, now, query="whitebox-keycloak") == ["whitebox"]
    assert titles(shot, now, query="quay.io") == ["whitebox"]
    renamed = replace(snapshot.groups[0], explanation="x", name="proj", ports=())
    process = renamed.members[1]
    assert isinstance(process, ProcessMember)
    only_name = replace(renamed, members=(replace(process, name="gunicorn", cmdline=("run",)),))
    assert titles(with_groups(snapshot, only_name), now, query="gunicorn") == ["proj"]


def test_search_ignores_container_members_without_a_command(
    snapshot: Snapshot, now: datetime
) -> None:
    container_only = replace(
        snapshot.groups[0],
        members=snapshot.groups[0].members[:1],
        ports=(),
        explanation="solo un container",
    )
    shot = with_groups(snapshot, container_only)
    assert titles(shot, now, query="uvicorn") == []
    assert titles(shot, now, query="whitebox") == ["whitebox"]


def test_combined_filters_all_apply(snapshot: Snapshot, now: datetime) -> None:
    groups = (
        make_group("api-idle", category=Category.DEV_SERVER, state=ActivityState.IDLE),
        make_group("api-busy", category=Category.DEV_SERVER, state=ActivityState.ACTIVE),
        make_group("api-ai", category=Category.AI_CLI, state=ActivityState.IDLE),
        make_group("web-idle", category=Category.DEV_SERVER, state=ActivityState.IDLE),
        make_group("api-risky", category=Category.DEV_SERVER, risk=Risk.DANGER),
    )
    shot = with_groups(snapshot, *groups)
    result = titles(
        shot,
        now,
        only_idle=True,
        categories=frozenset({Category.DEV_SERVER}),
        risks=frozenset({Risk.SAFE}),
        query="API",
    )
    assert result == ["api-idle"]
