"""Plain-text summary of a snapshot for ``wimm status``, in the active language."""

import re

from wimm.core.sizes import format_size
from wimm.i18n import N_, _
from wimm.model.enums import Pressure
from wimm.model.snapshot import Group, Snapshot
from wimm.redaction import redact_text

TOP_GROUPS = 5
# C0, DEL and C1 controls, zero-width and bidirectional marks: a name can neither drive the
# terminal (escape sequences, OSC 52) nor reorder or hide what the user reads.
CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2066-\u2069]+")
PRESSURE_LABELS = {
    Pressure.OK: N_("normale"),
    Pressure.WARNING: N_("attenzione"),
    Pressure.CRITICAL: N_("critica"),
}


def printable(*, text: str) -> str:
    """Redact credentials and replace control characters, so a name cannot drive the terminal."""
    return CONTROL_CHARACTERS.sub(repl=" ", string=redact_text(text=text)).strip()


def largest_groups(*, snapshot: Snapshot) -> tuple[Group, ...]:
    ordered = sorted(snapshot.groups, key=lambda group: group.memory.used, reverse=True)
    return tuple(ordered[:TOP_GROUPS])


def render_status(*, snapshot: Snapshot) -> str:
    """Return RAM, pressure, the five largest groups and the free disk space."""
    memory, disk = snapshot.memory, snapshot.disk
    lines = [
        _("Memoria: {used} usati su {total}").format(
            used=format_size(size=memory.used), total=format_size(size=memory.total)
        ),
        _("Pressione: {level}").format(level=_(PRESSURE_LABELS[snapshot.pressure])),
        _("Gruppi più grandi:"),
    ]
    lines += [
        f"  {printable(text=group.name)}: {format_size(size=group.memory.used)}"
        for group in largest_groups(snapshot=snapshot)
    ]
    lines.append(
        _("Disco: {free} liberi su {total} ({mount})").format(
            free=format_size(size=disk.free),
            total=format_size(size=disk.total),
            mount=printable(text=disk.mount),
        )
    )
    return "\n".join(lines)
