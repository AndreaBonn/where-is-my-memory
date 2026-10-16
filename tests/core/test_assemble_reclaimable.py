from datetime import timedelta

import pytest

from wimm.core.assemble import UserState, assemble_snapshot
from wimm.model.enums import ActionKind, ActivityState, Category, GroupId, Risk
from wimm.model.snapshot import ActionOffer

from .assemble_helpers import ACTIVE, NOW, UNKNOWN, build_input, draft, pair


def test_assemble_ignored_group_stays_listed_but_leaves_reclaimable_now() -> None:
    pairs = [pair(1, Category.DEV_SERVER, uss=60, swap=0), pair(2, Category.DEV_SERVER, uss=40)]
    drafts = [
        draft("g_1", name="alpha", category=Category.DEV_SERVER, pids=[1]),
        draft("g_2", name="beta", category=Category.DEV_SERVER, pids=[2]),
    ]
    user = UserState(ignored=frozenset({GroupId("g_1")}))

    snapshot = assemble_snapshot(inputs=build_input(drafts, pairs=pairs, user=user))

    flags = {group.name: group.ignored for group in snapshot.groups}
    assert flags == {"alpha": True, "beta": False}
    assert snapshot.reclaimable_now.ram == 40 + 10


@pytest.mark.parametrize(
    ("offset", "expected_active"),
    [(timedelta(hours=1), True), (timedelta(seconds=0), False), (-timedelta(hours=1), False)],
)
def test_assemble_snooze_is_kept_only_while_in_the_future_and_still_counts_as_reclaimable(
    offset: timedelta, expected_active: bool
) -> None:
    drafts = [draft("g_1", category=Category.DEV_SERVER, pids=[1])]
    user = UserState(snoozed_until={GroupId("g_1"): NOW + offset})

    snapshot = assemble_snapshot(
        inputs=build_input(drafts, pairs=[pair(1, Category.DEV_SERVER)], user=user)
    )

    (group,) = snapshot.groups
    assert group.snoozed_until == (NOW + offset if expected_active else None)
    assert snapshot.reclaimable_now.ram == 70


def test_assemble_group_without_snooze_entry_has_no_snooze() -> None:
    drafts = [draft("g_1", category=Category.DEV_SERVER, pids=[1])]

    (group,) = assemble_snapshot(
        inputs=build_input(drafts, pairs=[pair(1, Category.DEV_SERVER)])
    ).groups

    assert group.snoozed_until is None


def test_assemble_active_group_does_not_count_as_reclaimable() -> None:
    drafts = [draft("g_1", category=Category.DEV_SERVER, pids=[1])]
    snapshot = assemble_snapshot(
        inputs=build_input(drafts, pairs=[pair(1, Category.DEV_SERVER)], verdicts={1: ACTIVE})
    )

    (group,) = snapshot.groups
    assert group.activity.state is ActivityState.ACTIVE
    assert group.primary_action == ActionOffer(kind=ActionKind.PROCESS_TERMINATE, risk=Risk.CAUTION)
    assert snapshot.reclaimable_now.ram == 0


def test_assemble_unknown_group_does_not_count_as_reclaimable() -> None:
    drafts = [draft("g_1", category=Category.DEV_SERVER, pids=[1])]

    snapshot = assemble_snapshot(
        inputs=build_input(drafts, pairs=[pair(1, Category.DEV_SERVER)], verdicts={1: UNKNOWN})
    )

    assert snapshot.groups[0].activity.state is ActivityState.UNKNOWN
    assert snapshot.reclaimable_now.ram == 0


def test_assemble_idle_group_with_a_caution_action_does_not_count_as_reclaimable() -> None:
    foreground = pair(1, Category.DEV_SERVER, tpgid=77, pgid=77)
    drafts = [draft("g_1", category=Category.DEV_SERVER, pids=[1])]

    snapshot = assemble_snapshot(inputs=build_input(drafts, pairs=[foreground]))

    assert snapshot.groups[0].activity.state is ActivityState.IDLE
    assert snapshot.groups[0].primary_action == ActionOffer(
        kind=ActionKind.PROCESS_TERMINATE, risk=Risk.CAUTION
    )
    assert snapshot.reclaimable_now.ram == 0
