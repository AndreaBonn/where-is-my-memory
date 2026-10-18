from dataclasses import replace

import pytest

from wimm.core.memory import (
    container_memory,
    group_memory,
    memory_summary,
    pressure,
    pressure_with_psi,
    process_memory,
    reclaimable_now,
)
from wimm.model.enums import ActionKind, ActivityState, Category, GpuVendor, Pressure, Risk
from wimm.model.memory import DiskUsage, GpuMemory, MemorySummary, MemoryUse, Reclaimable
from wimm.model.raw import KernelMemory, PsiSample
from wimm.model.snapshot import ActionOffer, ContainerMember, Group

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
    browser = group(category=Category.BROWSER, members=(member(Category.BROWSER),))
    result = memory_summary(mem=meminfo(), groups=(project, browser))
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


def test_summary_splits_every_group_over_its_member_categories() -> None:
    uvicorn = member(Category.DEV_SERVER)
    claude = replace(member(Category.AI_CLI), memory=MemoryUse(used=700, reclaimable=0))
    folder = group(category=Category.DEV_SERVER, members=(uvicorn, claude))

    result = memory_summary(mem=meminfo(), groups=(folder,))

    assert dict(result.breakdown.categories) == {Category.DEV_SERVER: 100, Category.AI_CLI: 700}


def _breakdown_total(result: MemorySummary) -> int:
    b = result.breakdown
    return (
        sum(size for _, size in b.categories)
        + b.kernel_cache
        + b.shared_tmpfs
        + b.kernel_unreclaimable
        + b.zram
        + b.zswap
        + b.unattributed
    )


def _dev_group() -> Group:
    return group(members=(member(Category.DEV_SERVER),))


def test_memory_summary_new_voices_sum_to_used() -> None:
    mem = meminfo(
        mem_total=2000,
        mem_free=200,
        cached=300,
        buffers=40,
        s_reclaimable=60,
        shmem=50,
        s_unreclaim=70,
        kernel_stack=8,
        page_tables=12,
        zswap=30,
    )
    result = memory_summary(
        mem=mem, groups=(_dev_group(),), kernel=KernelMemory(zram=25, tmpfs_used=45)
    )
    breakdown = result.breakdown
    assert breakdown.shared_tmpfs == 45
    assert breakdown.kernel_unreclaimable == 90
    assert breakdown.zram == 25
    assert breakdown.zswap == 30
    assert breakdown.kernel_cache == 300 + 40 + 60 - 50
    assert breakdown.unattributed == 1800 - 100 - 350 - 45 - 90 - 25 - 30
    assert _breakdown_total(result) == mem.mem_total - mem.mem_free


def test_memory_summary_shared_memory_is_capped_by_shmem_and_counted_once() -> None:
    mem = meminfo(mem_total=2000, mem_free=200, cached=300, buffers=0, s_reclaimable=0, shmem=50)
    result = memory_summary(mem=mem, groups=(), kernel=KernelMemory(zram=0, tmpfs_used=500))
    assert result.breakdown.shared_tmpfs == 50
    assert _breakdown_total(result) == mem.mem_total - mem.mem_free


def test_memory_summary_without_kernel_data_has_zero_zram_and_tmpfs() -> None:
    result = memory_summary(mem=meminfo(), groups=())
    assert (result.breakdown.shared_tmpfs, result.breakdown.zram) == (0, 0)


def test_memory_summary_processes_over_total_leave_no_negative_voice() -> None:
    mem = meminfo(mem_total=300, mem_free=100, s_unreclaim=20, zswap=5)
    result = memory_summary(
        mem=mem, groups=(_dev_group(), _dev_group()), kernel=KernelMemory(zram=10, tmpfs_used=5)
    )
    breakdown = result.breakdown
    assert breakdown.unattributed == 0
    voices = (
        breakdown.kernel_cache,
        breakdown.shared_tmpfs,
        breakdown.kernel_unreclaimable,
        breakdown.zram,
        breakdown.zswap,
        *(size for _, size in breakdown.categories),
    )
    assert all(voice >= 0 for voice in voices)


@pytest.mark.parametrize(
    ("some", "full", "expected"),
    [
        (9.99, 4.99, Pressure.OK),
        (10.0, 0.0, Pressure.WARNING),
        (0.0, 5.0, Pressure.CRITICAL),
        (50.0, 5.0, Pressure.CRITICAL),
        (50.0, 4.0, Pressure.WARNING),
    ],
)
def test_pressure_uses_psi_when_present(some: float, full: float, expected: Pressure) -> None:
    psi = PsiSample(some_avg60=some, full_avg60=full)
    assert pressure_with_psi(level=Pressure.OK, psi=psi) is expected


def test_pressure_with_psi_keeps_the_worse_of_ram_disk_and_psi() -> None:
    calm = PsiSample(some_avg60=0.0, full_avg60=0.0)
    busy = PsiSample(some_avg60=12.0, full_avg60=0.0)
    assert pressure_with_psi(level=Pressure.CRITICAL, psi=busy) is Pressure.CRITICAL
    assert pressure_with_psi(level=Pressure.WARNING, psi=calm) is Pressure.WARNING
    assert pressure_with_psi(level=Pressure.OK, psi=calm) is Pressure.OK


@pytest.mark.parametrize("level", list(Pressure))
def test_pressure_without_psi_leaves_the_current_rule_unchanged(level: Pressure) -> None:
    assert pressure_with_psi(level=level, psi=None) is level


def test_summary_carries_the_video_memory_it_is_given() -> None:
    video = (GpuMemory(vendor=GpuVendor.NVIDIA, used_bytes=5, total_bytes=10),)

    assert memory_summary(mem=meminfo(), groups=(), video=video).video == video
    assert memory_summary(mem=meminfo(), groups=()).video == ()
