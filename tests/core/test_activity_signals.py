from datetime import datetime

import pytest

from wimm.core.activity import (
    EntityKind,
    EntitySample,
    is_measurable,
    kind_of,
    sample_is_active,
)
from wimm.model.enums import Category

from .activity_helpers import CONFIG, OTHER_QUAD, QUAD, sample


def test_kind_table_covers_every_category() -> None:
    expected = {
        Category.DEV_SERVER: EntityKind.SERVER,
        Category.DEV_PROCESS: EntityKind.PROCESS,
        Category.AI_CLI: EntityKind.PROCESS,
        Category.CONTAINER: EntityKind.CONTAINER,
        Category.BROWSER: EntityKind.UNMEASURABLE,
        Category.DESKTOP_APP: EntityKind.UNMEASURABLE,
        Category.TERMINAL: EntityKind.UNMEASURABLE,
        Category.SYSTEM: EntityKind.NOT_EVALUATED,
        Category.SESSION: EntityKind.NOT_EVALUATED,
        Category.SELF: EntityKind.NOT_EVALUATED,
        Category.OTHER: EntityKind.NOT_EVALUATED,
        Category.PROJECT: EntityKind.NOT_EVALUATED,
    }
    assert set(expected) == set(Category)
    assert {c: kind_of(category=c) for c in Category} == expected
    assert is_measurable(category=Category.CONTAINER)
    assert not is_measurable(category=Category.BROWSER)
    assert not is_measurable(category=Category.SYSTEM)


def test_entity_sample_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        EntitySample(taken_at=datetime(2026, 10, 16), cpu_time_s=0.0)


@pytest.mark.parametrize("kind", [EntityKind.SERVER, EntityKind.PROCESS, EntityKind.CONTAINER])
def test_cpu_threshold_is_strictly_greater(kind: EntityKind) -> None:
    prev = sample(0, cpu_time_s=10.0)
    # 1.0 s over 100 s is exactly 1.0% of a core: not active; any more is.
    at_threshold = sample(100, cpu_time_s=11.0)
    above = sample(100, cpu_time_s=11.001)
    assert not sample_is_active(prev=prev, curr=at_threshold, kind=kind, config=CONFIG)
    assert sample_is_active(prev=prev, curr=above, kind=kind, config=CONFIG)


def test_cpu_unmeasured_or_reset_is_not_activity() -> None:
    prev = sample(0, cpu_time_s=50.0)
    for curr in (sample(30, cpu_time_s=None), sample(30, cpu_time_s=5.0)):
        assert not sample_is_active(prev=prev, curr=curr, kind=EntityKind.PROCESS, config=CONFIG)
    assert not sample_is_active(
        prev=sample(0, cpu_time_s=None),
        curr=sample(30, cpu_time_s=60.0),
        kind=EntityKind.PROCESS,
        config=CONFIG,
    )


def test_non_positive_elapsed_time_is_not_activity() -> None:
    prev = sample(0, cpu_time_s=0.0)
    curr = sample(0, cpu_time_s=99.0, connections=frozenset({QUAD}))
    assert not sample_is_active(prev=prev, curr=curr, kind=EntityKind.SERVER, config=CONFIG)


def test_connection_present_in_two_consecutive_samples_is_not_new() -> None:
    prev = sample(0, connections=frozenset({QUAD}))
    curr = sample(30, connections=frozenset({QUAD}))
    assert not sample_is_active(prev=prev, curr=curr, kind=EntityKind.SERVER, config=CONFIG)


def test_new_time_wait_connection_is_activity() -> None:
    prev = sample(0, connections=frozenset({QUAD}))
    curr = sample(30, connections=frozenset({QUAD, OTHER_QUAD}))
    assert sample_is_active(prev=prev, curr=curr, kind=EntityKind.SERVER, config=CONFIG)


@pytest.mark.parametrize(
    ("before", "after"),
    [(frozenset({QUAD}), None), (None, frozenset({QUAD})), (None, None)],
)
def test_unmeasured_connections_give_no_connection_signal(
    before: frozenset[tuple[str, int, str, int]] | None,
    after: frozenset[tuple[str, int, str, int]] | None,
) -> None:
    prev = sample(0, connections=before)
    curr = sample(30, connections=after)
    assert not sample_is_active(prev=prev, curr=curr, kind=EntityKind.SERVER, config=CONFIG)


def test_closed_connection_alone_is_not_activity() -> None:
    prev = sample(0, connections=frozenset({QUAD}))
    curr = sample(30, connections=frozenset())
    assert not sample_is_active(prev=prev, curr=curr, kind=EntityKind.SERVER, config=CONFIG)


def test_connections_do_not_count_for_plain_processes() -> None:
    prev = sample(0)
    curr = sample(30, connections=frozenset({QUAD}))
    assert not sample_is_active(prev=prev, curr=curr, kind=EntityKind.PROCESS, config=CONFIG)


def test_server_cpu_alone_is_activity() -> None:
    prev = sample(0, cpu_time_s=0.0)
    curr = sample(30, cpu_time_s=30.0)
    assert sample_is_active(prev=prev, curr=curr, kind=EntityKind.SERVER, config=CONFIG)


def test_container_network_rate_threshold_is_strictly_greater() -> None:
    prev = sample(0, net_bytes=1000)
    at_limit = sample(10, net_bytes=1000 + 7000)  # exactly 700 B/s
    above = sample(10, net_bytes=1000 + 7001)
    below = sample(10, net_bytes=1000 + 6999)
    kind = EntityKind.CONTAINER
    assert not sample_is_active(prev=prev, curr=below, kind=kind, config=CONFIG)
    assert not sample_is_active(prev=prev, curr=at_limit, kind=kind, config=CONFIG)
    assert sample_is_active(prev=prev, curr=above, kind=kind, config=CONFIG)


def test_container_network_rate_does_not_depend_on_interval() -> None:
    kind = EntityKind.CONTAINER
    prev = sample(0, net_bytes=0)
    assert not sample_is_active(
        prev=prev, curr=sample(30, net_bytes=20000), kind=kind, config=CONFIG
    )
    assert sample_is_active(prev=prev, curr=sample(30, net_bytes=21001), kind=kind, config=CONFIG)


def test_container_without_net_counts_only_cpu() -> None:
    kind = EntityKind.CONTAINER
    quiet = sample(30, net_bytes=None, cpu_time_s=0.0)
    busy = sample(30, net_bytes=None, cpu_time_s=30.0)
    prev = sample(0, net_bytes=None)
    assert not sample_is_active(prev=prev, curr=quiet, kind=kind, config=CONFIG)
    assert sample_is_active(prev=prev, curr=busy, kind=kind, config=CONFIG)
    half_known = sample(30, net_bytes=10**9)
    assert not sample_is_active(prev=prev, curr=half_known, kind=kind, config=CONFIG)


def test_container_net_counter_going_backwards_is_ignored() -> None:
    prev = sample(0, net_bytes=10**9)
    curr = sample(30, net_bytes=0)
    assert not sample_is_active(prev=prev, curr=curr, kind=EntityKind.CONTAINER, config=CONFIG)


@pytest.mark.parametrize("kind", [EntityKind.UNMEASURABLE, EntityKind.NOT_EVALUATED])
def test_unmeasured_kinds_are_never_active(kind: EntityKind) -> None:
    curr = sample(30, cpu_time_s=99.0, connections=frozenset({QUAD}), foreground=True)
    assert not sample_is_active(prev=sample(0), curr=curr, kind=kind, config=CONFIG)
