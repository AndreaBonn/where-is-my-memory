from dataclasses import replace
from datetime import UTC, datetime

import pytest

from tests.core.helpers import process
from wimm.service.sampler_steps import (
    ProcessCycle,
    ProcessSamples,
    children_by_pid,
    cpu_deltas,
    post_order,
    subtree_cpu,
)


def test_children_by_pid_groups_processes_under_their_parent() -> None:
    processes = {
        pid: process(pid=pid, ppid=parent)
        for pid, parent in ((1, 0), (2, 1), (3, 1), (4, 2), (5, 0))
    }
    children = children_by_pid(processes=processes)
    assert children == {0: (1, 5), 1: (2, 3), 2: (4,)}


def test_post_order_and_subtree_cpu_include_each_descendant_once() -> None:
    children = {0: (1, 5), 1: (2, 3), 2: (4,)}
    order = post_order(pids=(1, 2, 3, 4, 5), children=children)
    assert set(order) == {1, 2, 3, 4, 5}
    assert order.index(4) < order.index(2) < order.index(1)
    assert order.index(3) < order.index(1)
    assert subtree_cpu(order=order, children=children, deltas={1: 1, 2: 2, 4: 4, 5: 5}) == {
        1: 7,
        2: 6,
        3: 0,
        4: 4,
        5: 5,
    }
    assert post_order(pids=(), children={}) == ()
    assert subtree_cpu(order=(), children={}, deltas={}) == {}


def test_cpu_deltas_require_matching_identity_and_available_counters() -> None:
    previous = {pid: process(pid=pid, create_time=1, cpu_time_s=10) for pid in range(1, 7)}
    current = {
        1: replace(previous[1], cpu_time_s=13),
        2: replace(previous[2], create_time=2, cpu_time_s=100),
        3: replace(previous[3], cpu_time_s=9),
        4: replace(previous[4], create_time=None, cpu_time_s=100),
        5: replace(previous[5], cpu_time_s=None),
        7: process(pid=7, create_time=1, cpu_time_s=50),
    }
    assert cpu_deltas(processes=current, previous=previous) == {1: 3, 3: 0}
    assert cpu_deltas(processes=current, previous={}) == {}


def test_cycle_indexes_descendant_ports_without_sibling_listeners() -> None:
    processes = {
        pid: process(pid=pid, ppid=parent) for pid, parent in ((1, 1), (2, 1), (3, 1), (4, 2))
    }
    cycle = ProcessCycle(
        processes=processes,
        ports={3: frozenset({8000}), 4: frozenset({9000})},
        sockets=None,
        now=datetime.now(tz=UTC),
    )
    assert cycle.subtree_ports == {
        1: frozenset({8000, 9000}),
        2: frozenset({9000}),
        3: frozenset({8000}),
        4: frozenset({9000}),
    }
    assert cycle.connections == {}


def test_post_order_handles_deep_trees_without_recursion() -> None:
    size = 1500
    children = {pid: (pid + 1,) for pid in range(size - 1)}
    order = post_order(pids=tuple(range(size)), children=children)
    assert order == tuple(reversed(range(size)))
    assert subtree_cpu(order=order, children=children, deltas={size - 1: 2})[0] == 2


@pytest.mark.parametrize("missed", [1, 2, 3])
def test_cpu_continuity_expires_after_more_than_two_absences(missed: int) -> None:
    samples = ProcessSamples()
    proc = process(pid=20, create_time=1, cpu_time_s=10)
    for cpu in (10, 12, *([None] * missed), 15):
        records = {} if cpu is None else {20: replace(proc, cpu_time_s=cpu)}
        cycle = ProcessCycle(processes=records, ports={}, sockets=None, now=datetime.now(tz=UTC))
        samples.prepare(cycle=cycle)
        if records:
            result = samples.sample(proc=records[20], cycle=cycle)
        samples.finish(processes=records)
    assert result.cpu_time_s == (0 if missed > 2 else 5)
