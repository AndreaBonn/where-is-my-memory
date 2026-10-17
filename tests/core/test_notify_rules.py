from datetime import timedelta

import pytest

from wimm.config import Config
from wimm.core import constants
from wimm.core.notify_rules import evaluate_notifications
from wimm.model.enums import ActivityState, Category
from wimm.model.snapshot import ActivityAssessment, ContainerMember, Snapshot

from .helpers import member
from .notify_helpers import GB, NOW, idle_since, make_group, make_snapshot, request, with_config

MIN_BYTES = constants.NOTIFY_MIN_BYTES


def _ids(snapshot: Snapshot, *, config: Config | None = None) -> list[str]:
    return [i.id for i in evaluate_notifications(request=request(snapshot, config=config)).intents]


def test_idle_group_over_threshold_notifies_with_stable_id_and_italian_text() -> None:
    snapshot = make_snapshot((make_group("g_1", name="whitebox", reclaimable=1_100_000_000),))

    result = evaluate_notifications(request=request(snapshot))

    (intent,) = result.intents
    assert intent.id == "idle-g_1"
    assert intent.group_id == "g_1"
    assert intent.title == "whitebox è inattivo da 3 h"
    assert intent.body == "1,1 GB di RAM recuperabile."


def test_idle_body_counts_members_by_kind() -> None:
    container = ContainerMember(
        id="c",
        name="c",
        image="i",
        state="running",
        mounts=(),
        memory=member(Category.DEV_PROCESS).memory,
        activity=idle_since(),
        actions=(),
    )
    members = (container, container, member(Category.DEV_SERVER), member(Category.DEV_PROCESS))
    snapshot = make_group("g_1", category=Category.PROJECT, reclaimable=GB, members=members)

    (intent,) = evaluate_notifications(request=request(make_snapshot((snapshot,)))).intents

    assert intent.body == "2 container, 1 server e 1 processo, 1,0 GB di RAM recuperabile."


def test_same_episode_over_two_cycles_notifies_once() -> None:
    snapshot = make_snapshot((make_group(),))
    first = evaluate_notifications(request=request(snapshot))

    second = evaluate_notifications(
        request=request(snapshot, state=first.state, now=NOW + timedelta(seconds=30))
    )

    assert len(first.intents) == 1
    assert second.intents == ()


def test_new_episode_of_same_group_notifies_again() -> None:
    first = evaluate_notifications(request=request(make_snapshot((make_group(),))))
    later = make_group(
        activity=ActivityAssessment(
            state=ActivityState.IDLE, since=NOW - timedelta(hours=2, minutes=1), reason="idle"
        )
    )
    second = evaluate_notifications(request=request(make_snapshot((later,)), state=first.state))

    assert [item.id for item in second.intents] == ["idle-g_1"]


def test_idle_five_groups_gives_three_plus_one_aggregate() -> None:
    sizes = (5, 4, 3, 2, 1)
    groups = tuple(
        make_group(f"g_{i}", name=f"n{i}", reclaimable=size * GB) for i, size in enumerate(sizes)
    )

    result = evaluate_notifications(request=request(make_snapshot(groups)))

    assert [item.id for item in result.intents] == [
        "idle-g_0",
        "idle-g_1",
        "idle-g_2",
        "idle-aggregate",
    ]
    aggregate = result.intents[-1]
    assert aggregate.title == "2 gruppi inattivi"
    assert aggregate.body == "3,0 GB di RAM recuperabile. Apri il pannello per vederli."
    assert aggregate.group_id is None


def test_aggregated_groups_are_not_renotified_next_cycle() -> None:
    groups = tuple(make_group(f"g_{i}", reclaimable=(5 - i) * GB) for i in range(5))
    first = evaluate_notifications(request=request(make_snapshot(groups)))

    second = evaluate_notifications(
        request=request(make_snapshot(groups), state=first.state, now=NOW + timedelta(minutes=1))
    )

    assert second.intents == ()


def test_hourly_limit_defers_idle_until_window_frees() -> None:
    groups = tuple(make_group(f"g_{i}", reclaimable=(5 - i) * GB) for i in range(5))
    first = evaluate_notifications(request=request(make_snapshot(groups[:3])))
    more = make_snapshot(groups[3:])

    blocked = evaluate_notifications(
        request=request(more, state=first.state, now=NOW + timedelta(minutes=59))
    )
    freed = evaluate_notifications(
        request=request(more, state=first.state, now=NOW + timedelta(minutes=60))
    )

    assert blocked.intents == ()
    assert [item.id for item in freed.intents] == ["idle-g_3", "idle-g_4"]


def test_ai_cli_idle_is_silent_by_default_and_notifies_when_enabled() -> None:
    snapshot = make_snapshot((make_group(category=Category.AI_CLI),))
    enabled = with_config(notify_categories=frozenset({Category.AI_CLI}))

    assert _ids(snapshot) == []
    assert _ids(snapshot, config=enabled) == ["idle-g_1"]


def test_desktop_app_idle_is_silent_by_default() -> None:
    assert _ids(make_snapshot((make_group(category=Category.DESKTOP_APP),))) == []


def test_system_category_is_not_among_the_notified_categories() -> None:
    # Config refuses protected categories in notify_categories, so this is the category
    # filter at work; the protection check in the rules is defence in depth behind it.
    snapshot = make_snapshot((make_group(category=Category.SYSTEM),))
    assert _ids(snapshot) == []


def test_ignored_group_is_silent_and_same_group_not_ignored_notifies() -> None:
    assert _ids(make_snapshot((make_group(ignored=True),))) == []
    assert _ids(make_snapshot((make_group(ignored=False),))) == ["idle-g_1"]


@pytest.mark.parametrize(
    ("offset", "expected"),
    [(timedelta(hours=1), []), (timedelta(0), ["idle-g_1"]), (-timedelta(hours=1), ["idle-g_1"])],
)
def test_snoozed_group_is_silent_only_while_in_the_future(
    offset: timedelta, expected: list[str]
) -> None:
    snapshot = make_snapshot((make_group(snoozed_until=NOW + offset),))
    assert _ids(snapshot) == expected


@pytest.mark.parametrize(
    ("hours", "expected"),
    [(1.99, []), (2.0, ["idle-g_1"]), (5.0, ["idle-g_1"])],
)
def test_idle_time_threshold_boundary(hours: float, expected: list[str]) -> None:
    snapshot = make_snapshot((make_group(activity=idle_since(hours=hours)),))
    assert _ids(snapshot) == expected


@pytest.mark.parametrize(("size", "expected"), [(MIN_BYTES - 1, []), (MIN_BYTES, ["idle-g_1"])])
def test_reclaimable_threshold_boundary(size: int, expected: list[str]) -> None:
    assert _ids(make_snapshot((make_group(reclaimable=size),))) == expected


@pytest.mark.parametrize("state", [ActivityState.ACTIVE, ActivityState.UNKNOWN])
def test_non_idle_group_never_notifies(state: ActivityState) -> None:
    since = None if state is ActivityState.UNKNOWN else NOW - timedelta(hours=5)
    activity = ActivityAssessment(state=state, since=since, reason="x")
    assert _ids(make_snapshot((make_group(activity=activity),))) == []


def test_notify_after_follows_configuration() -> None:
    snapshot = make_snapshot((make_group(activity=idle_since(hours=0.5)),))
    assert _ids(snapshot) == []
    assert _ids(snapshot, config=with_config(notify_after_s=600)) == ["idle-g_1"]
