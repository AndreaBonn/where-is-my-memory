from collections.abc import Sequence

from wimm.model.enums import ActivityState, Category, Pressure, Risk
from wimm.model.memory import DiskUsage, MemoryBreakdown, MemorySummary, MemoryUse, Reclaimable
from wimm.model.raw import MemInfo, RawProcess
from wimm.model.snapshot import ContainerMember, Group, Member

from .constants import PRESSURE_CRITICAL_PCT, PRESSURE_WARNING_PCT

PERCENT_SCALE = 100


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
        if group.category is not Category.PROJECT:
            totals[group.category] = totals.get(group.category, 0) + group.memory.used
            continue
        for member in group.members:
            category = (
                Category.CONTAINER if isinstance(member, ContainerMember) else member.category
            )
            totals[category] = totals.get(category, 0) + member.memory.used
    return tuple(sorted(totals.items(), key=lambda item: item[0].value))


def memory_summary(mem: MemInfo, groups: Sequence[Group]) -> MemorySummary:
    """Build the category breakdown and system totals in bytes.

    Parameters
    ----------
    mem : MemInfo
        System memory counters.
    groups : Sequence[Group]
        Disjoint groups, including protected entities, counted once.
    """
    categories = _category_totals(groups=groups)
    cache = mem.cached + mem.buffers + mem.s_reclaimable - mem.shmem
    unattributed = max(0, mem.mem_total - mem.mem_free - cache - sum(v for _, v in categories))
    breakdown = MemoryBreakdown(
        categories=categories, kernel_cache=cache, unattributed=unattributed
    )
    return MemorySummary(
        total=mem.mem_total,
        available=mem.mem_available,
        used=mem.mem_total - mem.mem_available,
        swap_total=mem.swap_total,
        swap_used=mem.swap_total - mem.swap_free,
        breakdown=breakdown,
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
