from dataclasses import replace
from datetime import datetime

import pytest

from tests.ui.viewmodel_helpers import (
    FIXTURE,
    make_group,
    titles,
    with_groups,
)
from wimm.model.enums import ActionKind, ActivityState, GroupId
from wimm.model.snapshot import (
    ProcessMember,
    Snapshot,
)
from wimm.serialize import snapshot_from_json
from wimm.ui.viewmodel import (
    build_rows,
)
from wimm.ui.views import RowFilters


@pytest.fixture
def snapshot() -> Snapshot:
    return snapshot_from_json(text=FIXTURE.read_text())


@pytest.fixture
def now(snapshot: Snapshot) -> datetime:
    return snapshot.taken_at


def test_group_row_says_the_growth_when_the_group_has_one(
    snapshot: Snapshot, now: datetime
) -> None:
    (row,) = build_rows(snapshot=snapshot, filters=RowFilters(), now=now)

    assert row.growth_text == "+620 MB in 2 h"


def test_group_row_without_growth_has_no_growth_text(snapshot: Snapshot, now: datetime) -> None:
    flat = with_groups(snapshot, replace(snapshot.groups[0], growth=None))

    (row,) = build_rows(snapshot=flat, filters=RowFilters(), now=now)

    assert row.growth_text is None


def test_fixture_group_row_reads_like_the_spec_mockup(snapshot: Snapshot, now: datetime) -> None:
    (row,) = build_rows(snapshot=snapshot, filters=RowFilters(), now=now)

    assert row.title == "whitebox"
    assert row.subtitle == "Progetto · non in uso da 5 h"
    assert row.detail == "Non lo usi da 5 ore: nessuno ci si collega."
    assert row.technical == (
        "nessuna connessione in ingresso e CPU media 0,1% negli ultimi 30 minuti · porte 8000, 8080"
    )
    assert row.is_idle
    assert (row.reclaimable, row.memory) == ("1,1 GB", "1,1 GB")
    assert (row.risk_text, row.risk_style) == ("Sicuro: non perdi nulla", "success")
    assert row.primary_action is not None
    assert (row.primary_action.label, row.primary_action.kind) == ("Ferma", ActionKind.GROUP_STOP)
    assert row.explanation.startswith("progetto compose 'whitebox'")
    assert (row.ignored, row.snoozed_until, row.snoozed_text) == (False, None, None)


def test_fixture_members_show_command_cwd_ports_image_and_mounts(
    snapshot: Snapshot, now: datetime
) -> None:
    container, process = build_rows(snapshot=snapshot, filters=RowFilters(), now=now)[0].members

    assert (container.key, container.kind, container.name) == (
        "2c9184903a37",
        "container",
        "whitebox-keycloak",
    )
    assert container.title == "Accesso utenti (whitebox-keycloak)"
    assert container.image == "quay.io/keycloak/keycloak:26.0.8"
    assert container.state == "running"
    assert container.mounts == (
        "bind: /home/bonn/projects/ai-whitebox-core/vault -> /opt/keycloak/vault",
    )
    assert (container.command, container.cwd, container.started) == (None, None, None)
    assert container.memory == "682 MB"
    assert [a.label for a in container.actions] == ["Ferma"]

    assert (process.key, process.kind, process.name) == ("941149", "process", "uvicorn")
    assert process.title == "Server web (uvicorn)"
    assert process.command == "uvicorn app:main --port 8000"
    assert process.cwd == "/home/bonn/projects/ai-whitebox-core"
    assert process.ports == "8000"
    assert process.started == "16/10 06:46"
    assert process.memory == "180 MB"
    assert process.activity == "non in uso da 5 h"
    assert [a.label for a in process.actions] == ["Termina"]


def test_member_command_quotes_arguments_with_spaces(snapshot: Snapshot, now: datetime) -> None:
    process = snapshot.groups[0].members[1]
    assert isinstance(process, ProcessMember)
    spaced = replace(process, cmdline=("node", "my app.js"), cwd=None)
    group = replace(snapshot.groups[0], members=(spaced,))

    (member,) = build_rows(snapshot=with_groups(snapshot, group), filters=RowFilters(), now=now)[
        0
    ].members

    assert member.command == "node 'my app.js'"
    assert member.cwd is None


def test_member_with_empty_cmdline_has_no_command(snapshot: Snapshot, now: datetime) -> None:
    process = snapshot.groups[0].members[1]
    assert isinstance(process, ProcessMember)
    group = replace(snapshot.groups[0], members=(replace(process, cmdline=()),))

    (member,) = build_rows(snapshot=with_groups(snapshot, group), filters=RowFilters(), now=now)[
        0
    ].members

    assert member.command is None


def test_group_without_ports_does_not_mention_ports(snapshot: Snapshot, now: datetime) -> None:
    quiet = make_group("quiet", reason="CPU sotto soglia")
    noisy = make_group("noisy", reason="CPU sotto soglia", ports=(3000,))
    multi = make_group("multi", reason="CPU sotto soglia", ports=(3000, 8000))

    rows = {
        r.title: r
        for r in build_rows(
            snapshot=with_groups(snapshot, quiet, noisy, multi), filters=RowFilters(), now=now
        )
    }

    assert rows["quiet"].technical == "CPU sotto soglia"
    assert rows["noisy"].technical == "CPU sotto soglia · porta 3000"
    assert rows["multi"].technical == "CPU sotto soglia · porte 3000, 8000"


def test_long_name_arrives_untruncated(snapshot: Snapshot, now: datetime) -> None:
    name = "n" * 200
    (row,) = build_rows(
        snapshot=with_groups(snapshot, make_group(name)), filters=RowFilters(), now=now
    )
    assert row.title == name


def test_rows_sorted_by_reclaimable_descending(snapshot: Snapshot, now: datetime) -> None:
    groups = (
        make_group("small", reclaimable=10),
        make_group("big", reclaimable=900),
        make_group("mid", reclaimable=500),
    )
    assert titles(with_groups(snapshot, *groups), now) == ["big", "mid", "small"]


def test_unused_programs_come_before_the_ones_in_use(snapshot: Snapshot, now: datetime) -> None:
    groups = (
        make_group("browser", reclaimable=900, state=ActivityState.UNKNOWN, since=None),
        make_group("busy", reclaimable=800, state=ActivityState.ACTIVE),
        make_group("idle-small", reclaimable=10),
        make_group("idle-big", reclaimable=500),
    )
    rows = build_rows(snapshot=with_groups(snapshot, *groups), filters=RowFilters(), now=now)

    assert [r.title for r in rows] == ["idle-big", "idle-small", "browser", "busy"]
    assert [r.is_idle for r in rows] == [True, True, False, False]


def test_ties_break_on_used_then_name_then_id(snapshot: Snapshot, now: datetime) -> None:
    groups = (
        make_group("Banana", reclaimable=5, used=10),
        make_group("apple", reclaimable=5, used=10),
        make_group("heavy", reclaimable=5, used=99),
        make_group("Banana", reclaimable=5, used=10, id=GroupId("id-Aaa")),
    )
    rows = build_rows(snapshot=with_groups(snapshot, *groups), filters=RowFilters(), now=now)
    assert [r.id for r in rows] == ["id-heavy", "id-apple", "id-Aaa", "id-Banana"]
