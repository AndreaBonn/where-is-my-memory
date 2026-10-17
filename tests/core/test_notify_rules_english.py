import pytest

from wimm.core.notify_rules import evaluate_notifications
from wimm.model.enums import Category

from .helpers import member
from .notify_helpers import GB, make_group, make_snapshot, request

pytestmark = pytest.mark.usefixtures("english")


def _groups(*, count: int) -> tuple:  # type: ignore[type-arg]
    return tuple(
        make_group(f"g_{i}", name=f"n{i}", reclaimable=(count - i) * GB) for i in range(count)
    )


def test_idle_notification_in_english_with_decimal_point() -> None:
    snapshot = make_snapshot((make_group("g_1", name="whitebox", reclaimable=1_100_000_000),))

    (intent,) = evaluate_notifications(request=request(snapshot)).intents

    assert intent.title == "whitebox is running but you haven't used it for 3 hours"
    assert (
        intent.body == "Closing it frees 1.1 GB of memory. You decide: it won't close on its own."
    )


def test_idle_body_lists_members_with_english_plurals() -> None:
    members = (member(Category.DEV_PROCESS), member(Category.DEV_PROCESS))
    snapshot = make_snapshot((make_group("g_1", members=members),))

    (intent,) = evaluate_notifications(request=request(snapshot)).intents

    assert intent.body.endswith("Inside: 2 processes.")


def test_aggregate_of_two_programs_is_plural_in_english() -> None:
    result = evaluate_notifications(request=request(make_snapshot(_groups(count=5))))

    aggregate = result.intents[-1]
    assert aggregate.title == "2 running programs you don't use"
    assert aggregate.body == "Closing them frees 3.0 GB of memory. Open the panel to see them."


def test_aggregate_of_one_program_is_singular_in_english() -> None:
    result = evaluate_notifications(request=request(make_snapshot(_groups(count=4))))

    aggregate = result.intents[-1]
    assert aggregate.title == "1 running program you don't use"
    assert aggregate.body == "Closing it frees 1.0 GB of memory. Open the panel to see it."


def test_pressure_notifications_in_english() -> None:
    groups = (make_group("g_b", name="visible", reclaimable=1 * GB),)
    snapshot = make_snapshot(
        groups, ram_free_pct=5, disk_free_pct=4, reclaimable_disk=3_200_000_000
    )

    by_id = {i.id: i for i in evaluate_notifications(request=request(snapshot)).intents}

    assert by_id["pressure-ram"].title == "Memory almost full (5% free)"
    assert by_id["pressure-ram"].body == "You can free up right away: visible 1.0 GB."
    assert by_id["pressure-disk"].title == "Disk almost full (4% free)"
    assert by_id["pressure-disk"].body == "You can free up 3.2 GB on the disk right away."


def test_pressure_without_candidates_points_to_the_panel() -> None:
    snapshot = make_snapshot(ram_free_pct=5, disk_free_pct=4)

    by_id = {i.id: i for i in evaluate_notifications(request=request(snapshot)).intents}

    assert by_id["pressure-ram"].body == "Open the panel to see what to close."
    assert by_id["pressure-disk"].body == "Open the panel to see what takes up space."
