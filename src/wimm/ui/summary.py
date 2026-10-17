from wimm.i18n import N_, _
from wimm.model.enums import Category
from wimm.model.snapshot import Snapshot

from .format import (
    CATEGORY_LABELS,
    PRESSURE_PLAIN,
    PRESSURE_TEXT,
    allocate_percents,
    format_round_size,
    format_size,
)
from .summary_status import ram_drives_pressure, safe_fields, status_fields
from .views import BarSegment, SummaryView

KERNEL_CACHE_NOTE = N_("La memoria di appoggio del sistema si libera da sola quando serve.")
KERNEL_CACHE_LABEL = N_("Memoria di appoggio del sistema")
OTHER_PROGRAMS_LABEL = N_("Altro")
OTHER_PROGRAMS_KEY = "other_programs"
# P3: the four largest categories by name, the rest folded into "Altri programmi".
LEGEND_CATEGORIES = 4
UNATTRIBUTED_LABEL = N_("Non attribuita")
FREE_LABEL = N_("Libera")


def _fraction(*, part: int, whole: int) -> float:
    return min(part / whole, 1.0) if whole > 0 else 0.0


def _segment_items(*, snapshot: Snapshot) -> list[tuple[str, str, int]]:
    breakdown = snapshot.memory.breakdown
    ranked = sorted(
        (
            (category, size)
            for category, size in breakdown.categories
            if size > 0 and category is not Category.OTHER
        ),
        key=lambda item: (-item[1], item[0].name),
    )
    items = [(c.name, _(CATEGORY_LABELS[c]), size) for c, size in ranked[:LEGEND_CATEGORIES]]
    # "Altro" also takes Category.OTHER, so the legend never shows the word twice.
    rest = sum(size for _category, size in ranked[LEGEND_CATEGORIES:]) + sum(
        size for category, size in breakdown.categories if category is Category.OTHER
    )
    if rest > 0:
        items.append((OTHER_PROGRAMS_KEY, _(OTHER_PROGRAMS_LABEL), rest))
    if breakdown.kernel_cache > 0:
        items.append(("kernel_cache", _(KERNEL_CACHE_LABEL), breakdown.kernel_cache))
    # Unattributed memory is always listed, even at zero (RF-02).
    items.append(("unattributed", _(UNATTRIBUTED_LABEL), breakdown.unattributed))
    # The snapshot has no MemFree: the remainder closes the bar on total memory.
    free = snapshot.memory.total - sum(size for _key, _label, size in items)
    if free > 0:
        items.append(("free", _(FREE_LABEL), free))
    return items


def _segments(*, snapshot: Snapshot) -> tuple[BarSegment, ...]:
    items = _segment_items(snapshot=snapshot)
    whole = sum(size for _key, _label, size in items)
    percents = allocate_percents(sizes=tuple(size for _key, _label, size in items))
    segments = []
    for (key, label, size), percent in zip(items, percents, strict=True):
        size_text = format_size(size=size)
        segments.append(
            BarSegment(
                key=key,
                label=label,
                size=size,
                size_text=size_text,
                percent=percent,
                fraction=_fraction(part=size, whole=whole),
                legend=f"{label}: {size_text}",
            )
        )
    return tuple(segments)


def _pressure_suffix(*, snapshot: Snapshot) -> str:
    """The pressure in words after the RAM details, only when the RAM is what drives it."""
    plain = PRESSURE_PLAIN[snapshot.pressure]
    # The normal level has no text: translating "" would return the catalog header.
    return f" · {_(plain)}" if plain and ram_drives_pressure(snapshot=snapshot) else ""


def _headlines(*, snapshot: Snapshot) -> dict[str, str]:
    """P2: memory and disk as round numbers in words, the details for whoever wants them."""
    memory, disk = snapshot.memory, snapshot.disk
    return {
        "ram_headline": (
            _("{used} usati su {total}").format(
                used=format_round_size(size=memory.used), total=format_round_size(size=memory.total)
            )
        ),
        "ram_details": (
            _("disponibili {available} · swap {used} su {total}").format(
                available=format_size(size=memory.available),
                used=format_size(size=memory.swap_used),
                total=format_size(size=memory.swap_total),
            )
            + _pressure_suffix(snapshot=snapshot)
        ),
        "disk_headline": (
            _("{free} liberi su {total}").format(
                free=format_round_size(size=disk.free), total=format_round_size(size=disk.total)
            )
        ),
    }


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
        **_headlines(snapshot=snapshot),
        reclaimable_ram=format_size(size=reclaimable.ram),
        reclaimable_disk=format_size(size=reclaimable.disk),
        pressure=snapshot.pressure,
        pressure_text=_(PRESSURE_TEXT[snapshot.pressure]),
        segments=_segments(snapshot=snapshot),
        kernel_cache_note=_(KERNEL_CACHE_NOTE),
        **status_fields(snapshot=snapshot),
        **safe_fields(snapshot=snapshot),
    )
