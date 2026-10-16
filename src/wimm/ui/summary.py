from wimm.model.snapshot import Snapshot

from .format import (
    CATEGORY_LABELS,
    PRESSURE_TEXT,
    allocate_percents,
    format_size,
    percent_text,
)
from .views import BarSegment, SummaryView

KERNEL_CACHE_NOTE = "La cache del kernel si libera da sola quando serve memoria."
KERNEL_CACHE_LABEL = "Cache del kernel"
UNATTRIBUTED_LABEL = "Non attribuita"
FREE_LABEL = "Libera"


def _fraction(*, part: int, whole: int) -> float:
    return min(part / whole, 1.0) if whole > 0 else 0.0


def _segment_items(*, snapshot: Snapshot) -> list[tuple[str, str, int]]:
    breakdown = snapshot.memory.breakdown
    ranked = sorted(
        ((category, size) for category, size in breakdown.categories if size > 0),
        key=lambda item: (-item[1], item[0].name),
    )
    items = [(c.name, CATEGORY_LABELS[c], size) for c, size in ranked]
    if breakdown.kernel_cache > 0:
        items.append(("kernel_cache", KERNEL_CACHE_LABEL, breakdown.kernel_cache))
    # Unattributed memory is always listed, even at zero (RF-02).
    items.append(("unattributed", UNATTRIBUTED_LABEL, breakdown.unattributed))
    # The snapshot has no MemFree: the remainder closes the bar on total memory.
    free = snapshot.memory.total - sum(size for _, _, size in items)
    if free > 0:
        items.append(("free", FREE_LABEL, free))
    return items


def _segments(*, snapshot: Snapshot) -> tuple[BarSegment, ...]:
    items = _segment_items(snapshot=snapshot)
    whole = sum(size for _, _, size in items)
    percents = allocate_percents(sizes=tuple(size for _, _, size in items))
    segments = []
    for (key, label, size), percent in zip(items, percents, strict=True):
        size_text = format_size(size=size)
        text = percent_text(percent=percent, size=size)
        segments.append(
            BarSegment(
                key=key,
                label=label,
                size=size,
                size_text=size_text,
                percent=percent,
                fraction=_fraction(part=size, whole=whole),
                percent_text=text,
                legend=f"{label}: {size_text} ({text})",
            )
        )
    return tuple(segments)


def build_summary(*, snapshot: Snapshot) -> SummaryView:
    """Build the panel header: RAM, swap, disk, reclaimable totals and the RAM bar segments."""
    memory, disk, reclaimable = snapshot.memory, snapshot.disk, snapshot.reclaimable_now
    return SummaryView(
        ram_used=format_size(size=memory.used),
        ram_total=format_size(size=memory.total),
        ram_available=format_size(size=memory.available),
        ram_fraction=_fraction(part=memory.used, whole=memory.total),
        swap_used=format_size(size=memory.swap_used),
        swap_total=format_size(size=memory.swap_total),
        disk_mount=disk.mount,
        disk_used=format_size(size=disk.used),
        disk_total=format_size(size=disk.total),
        disk_free=format_size(size=disk.free),
        disk_fraction=_fraction(part=disk.used, whole=disk.total),
        reclaimable_ram=format_size(size=reclaimable.ram),
        reclaimable_disk=format_size(size=reclaimable.disk),
        pressure=snapshot.pressure,
        pressure_text=PRESSURE_TEXT[snapshot.pressure],
        segments=_segments(snapshot=snapshot),
        kernel_cache_note=KERNEL_CACHE_NOTE,
    )
