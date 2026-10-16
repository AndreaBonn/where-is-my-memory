from dataclasses import replace

import pytest

from wimm.core.memory import (
    container_memory,
    group_memory,
    memory_summary,
    pressure,
    process_memory,
    reclaimable_now,
)
from wimm.model.enums import ActionKind, ActivityState, Category, Pressure, Risk
from wimm.model.memory import DiskUsage, MemoryUse, Reclaimable
from wimm.model.snapshot import ActionOffer, ContainerMember

from .helpers import group, member, meminfo, process


def test_process_memory_pss_uss_swap() -> None:
    assert process_memory(proc=process()) == MemoryUse(used=100, reclaimable=70)
    assert process_memory(proc=process(pss=None, uss=None, swap=None)) == MemoryUse(
        used=150, reclaimable=0
    )


@pytest.mark.parametrize(
    ("current", "inactive", "expected"), [(100, 30, 70), (10, 30, 0), (0, 0, 0)]
)
def test_container_memory(current: int, inactive: int, expected: int) -> None:
    assert container_memory(current_bytes=current, inactive_file_bytes=inactive) == MemoryUse(
        used=expected, reclaimable=expected
    )


def test_group_memory_sums_and_empty() -> None:
    assert group_memory(
        members=(member(Category.AI_CLI), member(Category.DEV_SERVER))
    ) == MemoryUse(used=200, reclaimable=140)
    assert group_memory(members=()) == MemoryUse(used=0, reclaimable=0)


def test_summary_splits_project_members_and_counts_other_groups_once() -> None:
    container = ContainerMember(
        id="c",
        name="db",
        image="pg",
        state="running",
        memory=MemoryUse(used=250, reclaimable=250),
        mounts=(),
        activity=group().activity,
        actions=(),
    )
    project = group(category=Category.PROJECT, members=(member(Category.DEV_SERVER), container))
    result = memory_summary(mem=meminfo(), groups=(project, group(category=Category.BROWSER)))
    assert result.used == 700
    assert (result.total, result.available, result.swap_total, result.swap_used) == (
        1000,
        300,
        200,
        50,
    )
    assert dict(result.breakdown.categories) == {
        Category.DEV_SERVER: 100,
        Category.CONTAINER: 250,
        Category.BROWSER: 100,
    }
    assert result.breakdown.kernel_cache == 140
    assert result.breakdown.unattributed == 310


def test_summary_clamps_unattributed_and_empty_groups() -> None:
    assert (
        memory_summary(
            mem=meminfo(mem_total=200, mem_available=50), groups=(group(),)
        ).breakdown.unattributed
        == 0
    )
    result = memory_summary(mem=meminfo(), groups=())
    assert result.breakdown.categories == ()
    assert result.breakdown.unattributed == 760


@pytest.mark.parametrize(
    ("available", "free", "expected"),
    [
        (15, 15, Pressure.OK),
        (14, 90, Pressure.WARNING),
        (90, 14, Pressure.WARNING),
        (10, 90, Pressure.WARNING),
        (9, 90, Pressure.CRITICAL),
        (90, 9, Pressure.CRITICAL),
        (0, 90, Pressure.CRITICAL),
        (100, 100, Pressure.OK),
    ],
)
def test_pressure_boundaries(available: int, free: int, expected: Pressure) -> None:
    disk = DiskUsage(mount="/", total=100, used=100 - free, free=free)
    assert pressure(mem=meminfo(mem_total=100, mem_available=available), disk=disk) is expected


def test_pressure_custom_thresholds_and_zero_totals() -> None:
    disk = DiskUsage(mount="/", total=100, used=75, free=25)
    assert pressure(mem=meminfo(), disk=disk, warning_pct=40, critical_pct=20) is Pressure.WARNING
    with pytest.raises(ValueError, match="total"):
        pressure(mem=meminfo(mem_total=0), disk=disk)
    with pytest.raises(ValueError, match="total"):
        pressure(mem=meminfo(), disk=replace(disk, total=0))


def test_reclaimable_requires_idle_safe_primary_not_ignored() -> None:
    safe = group(primary_action=ActionOffer(kind=ActionKind.GROUP_STOP, risk=Risk.SAFE))
    active = replace(safe.activity, state=ActivityState.ACTIVE)
    unknown = replace(safe.activity, state=ActivityState.UNKNOWN)
    caution = ActionOffer(kind=ActionKind.GROUP_STOP, risk=Risk.CAUTION)
    groups = (
        safe,
        replace(safe, ignored=True),
        replace(safe, activity=active),
        replace(safe, activity=unknown),
        replace(safe, primary_action=caution),
        group(),
    )
    assert reclaimable_now(groups=groups) == Reclaimable(ram=70, disk=0)
    assert reclaimable_now(groups=(), disk_bytes=123) == Reclaimable(ram=0, disk=123)
