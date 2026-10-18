from collections.abc import Sequence

from wimm.model.enums import ActivityState, Category, Pressure, Risk
from wimm.model.memory import DiskUsage, MemoryBreakdown, MemorySummary, MemoryUse, Reclaimable
from wimm.model.raw import KernelMemory, MemInfo, PsiSample, RawProcess
from wimm.model.snapshot import ContainerMember, Group, Member

from .constants import (
    PRESSURE_CRITICAL_PCT,
    PRESSURE_WARNING_PCT,
    PSI_FULL_CRITICAL_AVG60,
    PSI_SOME_WARNING_AVG60,
)

PERCENT_SCALE = 100
NO_KERNEL_MEMORY = KernelMemory(zram=0, tmpfs_used=0)
PRESSURE_SEVERITY = (Pressure.OK, Pressure.WARNING, Pressure.CRITICAL)


def process_memory(proc: RawProcess) -> MemoryUse:
    """Return PSS and USS plus swap; missing PSS falls back to RSS.

    Parameters
    ----------
    proc : RawProcess
        Collected process measurements; missing USS or swap contributes zero.
    """
    return MemoryUse(
        used=proc.pss if proc.pss is not None else proc.rss,
        reclaimable=(proc.uss or 0) + (proc.swap or 0),
    )


def container_memory(current_bytes: int, inactive_file_bytes: int) -> MemoryUse:
    """Return Docker working-set memory, clamped for non-atomic measurements.

    Parameters
    ----------
    current_bytes : int
        Cgroup memory.current measurement.
    inactive_file_bytes : int
        Cgroup memory.stat inactive_file measurement.
    """
    used = max(0, current_bytes - inactive_file_bytes)
    return MemoryUse(used=used, reclaimable=used)


def group_memory(members: Sequence[Member]) -> MemoryUse:
    """Sum member memory without counting shared pages as private memory.

    Parameters
    ----------
    members : Sequence[Member]
        Process and container members with computed memory.
    """
    return MemoryUse(
        used=sum(member.memory.used for member in members),
        reclaimable=sum(member.memory.reclaimable for member in members),
    )


def _category_totals(groups: Sequence[Group]) -> tuple[tuple[Category, int], ...]:
    totals: dict[Category, int] = {}
    for group in groups:
        for member in group.members:
            category = (
                Category.CONTAINER if isinstance(member, ContainerMember) else member.category
            )
            totals[category] = totals.get(category, 0) + member.memory.used
    return tuple(sorted(totals.items(), key=lambda item: item[0].value))


def _breakdown(
    mem: MemInfo, categories: tuple[tuple[Category, int], ...], kernel: KernelMemory
) -> MemoryBreakdown:
    cache = mem.cached + mem.buffers + mem.s_reclaimable - mem.shmem
    shared = min(mem.shmem, kernel.tmpfs_used)
    unreclaimable = mem.s_unreclaim + mem.kernel_stack + mem.page_tables
    explained = (
        cache + shared + unreclaimable + kernel.zram + mem.zswap + sum(v for _, v in categories)
    )
    return MemoryBreakdown(
        categories=categories,
        kernel_cache=cache,
        unattributed=max(0, mem.mem_total - mem.mem_free - explained),
        shared_tmpfs=shared,
        kernel_unreclaimable=unreclaimable,
        zram=kernel.zram,
        zswap=mem.zswap,
    )


def memory_summary(
    mem: MemInfo, groups: Sequence[Group], kernel: KernelMemory = NO_KERNEL_MEMORY
) -> MemorySummary:
    """Build the category breakdown and system totals in bytes.

    Every voice is a disjoint share of `MemTotal - MemFree`; shared memory is removed
    from the kernel cache and reported once as its own voice. What no voice explains
    is "unattributed", clamped at zero.

    Parameters
    ----------
    mem : MemInfo
        System memory counters.
    groups : Sequence[Group]
        Disjoint groups, including protected entities, counted once.
    kernel : KernelMemory
        zram and tmpfs usage; zero when the collector had nothing.
    """
    return MemorySummary(
        total=mem.mem_total,
        available=mem.mem_available,
        used=mem.mem_total - mem.mem_available,
        swap_total=mem.swap_total,
        swap_used=mem.swap_total - mem.swap_free,
        breakdown=_breakdown(mem=mem, categories=_category_totals(groups=groups), kernel=kernel),
    )


def pressure(
    mem: MemInfo,
    disk: DiskUsage,
    warning_pct: float = PRESSURE_WARNING_PCT,
    critical_pct: float = PRESSURE_CRITICAL_PCT,
) -> Pressure:
    """Return the worse pressure; strictly below a threshold enters its state.

    Parameters
    ----------
    mem : MemInfo
        Available RAM and total RAM; a zero total raises ValueError.
    disk : DiskUsage
        Free and total disk bytes; a zero total raises ValueError.
    warning_pct, critical_pct : float
        Strict lower bounds: exactly 15% is OK and exactly 10% is warning by default.
    """
    if not mem.mem_total or not disk.total:
        raise ValueError("Memory and disk totals must be nonzero")
    ram_pct = PERCENT_SCALE * mem.mem_available / mem.mem_total
    disk_pct = PERCENT_SCALE * disk.free / disk.total
    available_pct = min(ram_pct, disk_pct)
    if available_pct < critical_pct:
        return Pressure.CRITICAL
    if available_pct < warning_pct:
        return Pressure.WARNING
    return Pressure.OK


def _psi_level(psi: PsiSample) -> Pressure:
    if psi.full_avg60 >= PSI_FULL_CRITICAL_AVG60:
        return Pressure.CRITICAL
    if psi.some_avg60 >= PSI_SOME_WARNING_AVG60:
        return Pressure.WARNING
    return Pressure.OK


def pressure_with_psi(level: Pressure, psi: PsiSample | None) -> Pressure:
    """Return the worse of a RAM/disk pressure level and the PSI level.

    Parameters
    ----------
    level : Pressure
        State from `pressure` (RAM and disk thresholds).
    psi : PsiSample | None
        Memory PSI averages; None keeps `level` unchanged.
    """
    if psi is None:
        return level
    return max(level, _psi_level(psi=psi), key=PRESSURE_SEVERITY.index)


def reclaimable_now(groups: Sequence[Group], disk_bytes: int = 0) -> Reclaimable:
    """Sum idle, non-ignored groups whose primary action is safe.

    Parameters
    ----------
    groups : Sequence[Group]
        Groups with activity and action assessments already assigned.
    disk_bytes : int
        Reclaimable disk bytes from a disk report; zero until one is available.
    """
    ram = sum(
        group.memory.reclaimable
        for group in groups
        if group.activity.state is ActivityState.IDLE
        and not group.ignored
        and group.primary_action is not None
        and group.primary_action.risk is Risk.SAFE
    )
    return Reclaimable(ram=ram, disk=disk_bytes)
