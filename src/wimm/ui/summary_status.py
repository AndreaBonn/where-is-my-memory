"""The status sentence (P1) and the "free without risk" button (P4) of the summary."""

from types import MappingProxyType

from wimm.model.enums import ActivityState, Pressure, Risk
from wimm.model.snapshot import Group, Snapshot

from .format import format_size

STATUS_TITLES = MappingProxyType(
    {
        Pressure.OK: "Il computer sta bene",
        Pressure.WARNING: "La memoria si sta riempiendo",
        Pressure.CRITICAL: "La memoria è quasi finita",
    }
)
# libadwaita style classes, the same the risk badges use.
STATUS_LEVELS = MappingProxyType(
    {Pressure.OK: "success", Pressure.WARNING: "warning", Pressure.CRITICAL: "error"}
)
# The pressure is the worse of RAM and disk (core.memory.pressure): the sentence names
# the one that drives it, or a full disk would read as a memory problem.
DISK_TITLES = MappingProxyType(
    {
        Pressure.OK: "Il computer sta bene",
        Pressure.WARNING: "Il disco si sta riempiendo",
        Pressure.CRITICAL: "Il disco è quasi pieno",
    }
)
DISK_TEXT = "Fai spazio dalla scheda Disco: lì trovi cosa si può cancellare."
NOTHING_SAFE_TEXT = "Non c'è niente da chiudere senza rischi."
NOTHING_SAFE_LABEL = "Niente da liberare senza rischi"
NAMED_GROUPS = 3


def _safe_idle_groups(*, snapshot: Snapshot) -> list[Group]:
    """The groups "Ferma tutti" stops: the ones summed by reclaimable_now (RF-01, RF-24)."""
    chosen = [
        group
        for group in snapshot.groups
        if group.activity.state is ActivityState.IDLE
        and not group.ignored
        and group.primary_action is not None
        and group.primary_action.risk is Risk.SAFE
    ]
    return sorted(chosen, key=lambda g: (-g.memory.reclaimable, g.name.casefold(), g.id))


def _names(*, groups: list[Group]) -> str:
    names = [g.name for g in groups[:NAMED_GROUPS]]
    extra = len(groups) - len(names)
    if extra == 1:
        return f"{', '.join(names)} e un altro"
    if extra > 1:
        return f"{', '.join(names)} e altri {extra}"
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} e {names[-1]}"


def ram_drives_pressure(*, snapshot: Snapshot) -> bool:
    """True when the RAM, not the disk, has the smaller free share."""
    memory, disk = snapshot.memory, snapshot.disk
    if not memory.total or not disk.total:
        return True
    return memory.available * disk.total <= disk.free * memory.total


def status_fields(*, snapshot: Snapshot) -> dict[str, str]:
    """Title, sentence and style of the status line; the amount is the safe one only."""
    level = STATUS_LEVELS[snapshot.pressure]
    if snapshot.pressure is not Pressure.OK and not ram_drives_pressure(snapshot=snapshot):
        title = DISK_TITLES[snapshot.pressure]
        return {"status_title": title, "status_text": DISK_TEXT, "status_level": level}
    ram = snapshot.reclaimable_now.ram
    # Same condition as the button: the sentence never offers what the button cannot do.
    text = (
        f"Puoi liberare {format_size(size=ram)} chiudendo programmi che non usi. "
        "Niente si chiude senza il tuo consenso."
        if ram > 0 and _safe_idle_groups(snapshot=snapshot)
        else NOTHING_SAFE_TEXT
    )
    return {
        "status_title": STATUS_TITLES[snapshot.pressure],
        "status_text": text,
        "status_level": level,
    }


def safe_fields(*, snapshot: Snapshot) -> dict[str, str]:
    """Label and caption of the button that stops every idle safe group (P4, RF-24)."""
    ram = snapshot.reclaimable_now.ram
    groups = _safe_idle_groups(snapshot=snapshot)
    if ram <= 0 or not groups:
        return {"safe_label": NOTHING_SAFE_LABEL, "safe_text": ""}
    verb = "lo usi" if len(groups) == 1 else "li usi"
    return {
        "safe_label": f"Libera {format_size(size=ram)} senza rischi",
        "safe_text": f"Ferma {_names(groups=groups)}: non {verb} e non perdi nulla.",
    }
