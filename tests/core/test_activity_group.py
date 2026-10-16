from wimm.core.activity import (
    GroupMember,
    assess_group_activity,
)
from wimm.model.enums import ActivityState
from wimm.model.snapshot import ActivityAssessment

from .activity_helpers import at


def verdict(state: ActivityState, since_offset: float | None = None) -> ActivityAssessment:
    return ActivityAssessment(
        state=state,
        since=None if since_offset is None else at(since_offset),
        reason="motivo",
    )


def member(
    state: ActivityState, since_offset: float | None = None, *, measurable: bool = True
) -> GroupMember:
    return GroupMember(assessment=verdict(state, since_offset), measurable=measurable)


def test_group_active_when_any_member_is_active() -> None:
    members = (
        member(ActivityState.IDLE, -900),
        member(ActivityState.ACTIVE, -300),
        member(ActivityState.ACTIVE, -600),
    )
    result = assess_group_activity(members=members)
    assert (result.state, result.since) == (ActivityState.ACTIVE, at(-600))
    assert result.reason == "2 membri attivi su 3 misurabili"


def test_group_idle_takes_the_most_recent_since() -> None:
    members = (member(ActivityState.IDLE, -7200), member(ActivityState.IDLE, -3600))
    result = assess_group_activity(members=members)
    assert (result.state, result.since) == (ActivityState.IDLE, at(-3600))
    assert result.reason == "entrambi i membri misurabili sono inattivi"


def test_group_of_unmeasurable_members_is_unknown() -> None:
    members = (
        member(ActivityState.UNKNOWN, measurable=False),
        member(ActivityState.UNKNOWN, measurable=False),
    )
    result = assess_group_activity(members=members)
    assert (result.state, result.since, result.reason) == (
        ActivityState.UNKNOWN,
        None,
        "nessun membro misurabile",
    )


def test_group_ignores_unmeasurable_members_when_deciding_idle() -> None:
    members = (member(ActivityState.IDLE, -100), member(ActivityState.UNKNOWN, measurable=False))
    assert assess_group_activity(members=members).state is ActivityState.IDLE


def test_group_with_member_still_observed_is_not_idle() -> None:
    members = (member(ActivityState.IDLE, -100), member(ActivityState.UNKNOWN))
    result = assess_group_activity(members=members)
    assert result.state is ActivityState.UNKNOWN
    assert result.reason == "attività di almeno uno dei 2 membri misurabili ancora non determinata"


def test_group_active_wins_over_member_still_observed() -> None:
    members = (member(ActivityState.ACTIVE, -100), member(ActivityState.UNKNOWN))
    assert assess_group_activity(members=members).state is ActivityState.ACTIVE


def test_empty_group_is_unknown() -> None:
    assert assess_group_activity(members=()).state is ActivityState.UNKNOWN
