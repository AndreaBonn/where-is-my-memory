"""The top of the Panoramica: what frees without losing anything, memory and disk in one."""

from wimm.i18n import N_, _
from wimm.model.snapshot import Snapshot

from .disk_texts import NOTHING_SAFE_TEXT, SAFE_HEADLINE, DiskTotals, review_text
from .format import format_size
from .summary_status import offered_ram, safe_fields

NOTHING_IN_MEMORY_TEXT = N_("Niente da liberare in memoria senza perdere qualcosa")
UNCHECKED_DISK_TEXT = N_("Il disco non è ancora stato controllato: per ora conta solo la memoria.")
RAM_PART = N_("{size} di memoria")
DISK_PART = N_("{size} di disco")
PART_SEPARATOR = " · "


def _details(*, ram: int, disk: DiskTotals | None) -> str:
    """The split of the headline amount; a part that frees nothing is left out."""
    if disk is None:
        return _(UNCHECKED_DISK_TEXT)
    parts = [
        _(template).format(size=format_size(size=size))
        for template, size in ((RAM_PART, ram), (DISK_PART, disk.safe))
        if size > 0
    ]
    return PART_SEPARATOR.join(parts)


def reclaim_fields(*, snapshot: Snapshot, disk: DiskTotals | None) -> dict[str, str]:
    """Headline, split, the two buttons and what else frees at a cost.

    ``disk`` is None before the first disk scan: the disk is then unchecked, never zero.
    The amounts are the ones the two buttons free: the idle safe groups and the safe
    disk rows of the Disco page.
    """
    ram = offered_ram(snapshot=snapshot)
    disk_safe = 0 if disk is None else disk.safe
    total = ram + disk_safe
    if total > 0:
        headline = _(SAFE_HEADLINE).format(size=format_size(size=total))
    else:
        # An unchecked disk is not an empty one: only the memory can be said to hold nothing.
        headline = _(NOTHING_SAFE_TEXT if disk is not None else NOTHING_IN_MEMORY_TEXT)
    disk_label = (
        _("Libera {size} di disco").format(size=format_size(size=disk_safe)) if disk_safe else ""
    )
    return {
        "reclaim_headline": headline,
        "reclaim_details": _details(ram=ram, disk=disk) if total > 0 or disk is None else "",
        "disk_safe_label": disk_label,
        "review_text": review_text(totals=disk),
        **safe_fields(snapshot=snapshot),
    }
