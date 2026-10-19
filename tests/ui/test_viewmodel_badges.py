from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from tests.ui.viewmodel_helpers import FIXTURE, make_group, titles, with_groups
from wimm.model.enums import ActionKind, ActivityState, Category, Risk
from wimm.model.snapshot import (
    ActionOffer,
    ProcessMember,
    Snapshot,
)
from wimm.serialize import snapshot_from_json
from wimm.ui.viewmodel import (
    build_rows,
    empty_state,
)
from wimm.ui.views import EmptyKind, RowFilters


@pytest.fixture
def snapshot() -> Snapshot:
    return snapshot_from_json(text=FIXTURE.read_text())


@pytest.fixture
def now(snapshot: Snapshot) -> datetime:
    return snapshot.taken_at


def test_protected_groups_never_appear_in_the_overview(snapshot: Snapshot, now: datetime) -> None:
    protected = make_group("gnome", category=Category.SESSION, risk=None)
    system = make_group("kernel", category=Category.SYSTEM, risk=None)
    own = make_group("wimm", category=Category.SELF, risk=None)
    normal = make_group("srv")
    shot = with_groups(snapshot, protected, system, own, normal)

    assert titles(shot, now) == ["srv"]
    assert titles(shot, now, query="gnome") == []
    state = empty_state(snapshot=shot, filters=RowFilters(query="gnome"))
    assert state is not None
    assert state.kind is EmptyKind.NO_RESULTS


@pytest.mark.parametrize(
    ("risk", "text", "style", "label"),
    [
        (Risk.SAFE, "Sicuro: non perdi nulla", "success", "Ferma"),
        (Risk.CAUTION, "Attenzione: puoi perdere lavoro", "warning", "Ferma"),
        (Risk.DANGER, "Pericolo: cancella dati", "error", "Ferma"),
    ],
)
def test_badge_and_button_for_each_risk(
    snapshot: Snapshot, now: datetime, risk: Risk, text: str, style: str, label: str
) -> None:
    (row,) = build_rows(
        snapshot=with_groups(snapshot, make_group(risk=risk)), filters=RowFilters(), now=now
    )

    assert (row.risk, row.risk_text, row.risk_style) == (risk, text, style)
    assert row.primary_action is not None
    assert (row.primary_action.label, row.primary_action.risk) == (label, risk)


def test_actionable_group_without_primary_uses_riskiest_member_action(
    snapshot: Snapshot, now: datetime
) -> None:
    process = snapshot.groups[0].members[1]
    assert isinstance(process, ProcessMember)
    offers = (
        ActionOffer(kind=ActionKind.PROCESS_KILL, risk=Risk.SAFE),
        ActionOffer(kind=ActionKind.PROCESS_KILL, risk=Risk.DANGER),
        ActionOffer(kind=ActionKind.PROCESS_KILL, risk=Risk.CAUTION),
    )
    risky = replace(process, actions=offers)
    with_actions = replace(snapshot.groups[0], primary_action=None, members=(risky,))
    no_actions = make_group("idle-none", risk=None)

    rows = {
        r.title: r
        for r in build_rows(
            snapshot=with_groups(snapshot, with_actions, no_actions), filters=RowFilters(), now=now
        )
    }

    assert (rows["whitebox"].risk_text, rows["whitebox"].primary_action) == (
        "Pericolo: cancella dati",
        None,
    )
    assert (rows["idle-none"].risk_text, rows["idle-none"].risk_style) == (
        "Nessuna azione",
        "dim-label",
    )


def test_subtitle_for_each_activity_state(snapshot: Snapshot, now: datetime) -> None:
    groups = (
        make_group("a", category=Category.DEV_SERVER, state=ActivityState.ACTIVE),
        make_group(
            "b",
            category=Category.BROWSER,
            state=ActivityState.UNKNOWN,
            since=None,
            reason="attività non misurabile per i browser",
        ),
        make_group(
            "c",
            category=Category.AI_CLI,
            state=ActivityState.UNKNOWN,
            since=None,
            reason="in osservazione da 4 minuti",
        ),
    )
    rows = {
        r.title: r.subtitle
        for r in build_rows(snapshot=with_groups(snapshot, *groups), filters=RowFilters(), now=now)
    }
    assert rows == {
        "a": "Server di sviluppo · in uso",
        "b": "Browser · attività non misurabile",
        "c": "Assistente AI · in osservazione",
    }


def test_snooze_text_only_while_in_the_future(snapshot: Snapshot, now: datetime) -> None:
    future = now + timedelta(hours=1)
    groups = (
        make_group("future", snoozed_until=future),
        make_group("tomorrow", snoozed_until=datetime(2026, 10, 17, 14, 30, tzinfo=now.tzinfo)),
        make_group("past", snoozed_until=now - timedelta(minutes=1)),
        make_group("ignored", ignored=True),
    )
    rows = {
        r.title: r
        for r in build_rows(snapshot=with_groups(snapshot, *groups), filters=RowFilters(), now=now)
    }

    assert rows["future"].snoozed_until == future
    assert rows["future"].snoozed_text == "avvisi in pausa fino alle 11:30"
    assert rows["tomorrow"].snoozed_text == "avvisi in pausa fino al 17/10 alle 14:30"
    assert (rows["past"].snoozed_until, rows["past"].snoozed_text) == (None, None)
    assert rows["ignored"].ignored is True
    assert rows["future"].ignored is False
