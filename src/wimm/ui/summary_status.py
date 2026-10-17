"""The status sentence (P1) and the "free without risk" button (P4) of the summary."""

from types import MappingProxyType

from wimm.i18n import N_, _, ngettext
from wimm.model.enums import ActivityState, Pressure, Risk
from wimm.model.snapshot import Group, Snapshot

from .format import format_size

STATUS_TITLES = MappingProxyType(
    {
        Pressure.OK: N_("Il computer sta bene"),
        Pressure.WARNING: N_("La memoria si sta riempiendo"),
        Pressure.CRITICAL: N_("La memoria è quasi finita"),
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
        Pressure.OK: N_("Il computer sta bene"),
        Pressure.WARNING: N_("Il disco si sta riempiendo"),
        Pressure.CRITICAL: N_("Il disco è quasi pieno"),
    }
)
DISK_TEXT = N_("Fai spazio dalla scheda Disco: lì trovi cosa si può cancellare.")
NOTHING_SAFE_TEXT = N_("Non c'è niente da chiudere senza rischi.")
NOTHING_SAFE_LABEL = N_("Niente da liberare senza rischi")
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
        return _("{names} e un altro").format(names=", ".join(names))
    if extra > 1:
        return _("{names} e altri {count}").format(names=", ".join(names), count=extra)
    if len(names) == 1:
        return names[0]
    return _("{others} e {last}").format(others=", ".join(names[:-1]), last=names[-1])


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
        title = _(DISK_TITLES[snapshot.pressure])
        return {"status_title": title, "status_text": _(DISK_TEXT), "status_level": level}
    ram = snapshot.reclaimable_now.ram
    # Same condition as the button: the sentence never offers what the button cannot do.
    text = (
        _(
            "Puoi liberare {size} chiudendo programmi che non usi. "
            "Niente si chiude senza il tuo consenso."
        ).format(size=format_size(size=ram))
        if ram > 0 and _safe_idle_groups(snapshot=snapshot)
        else _(NOTHING_SAFE_TEXT)
    )
    return {
        "status_title": _(STATUS_TITLES[snapshot.pressure]),
        "status_text": text,
        "status_level": level,
    }


def safe_fields(*, snapshot: Snapshot) -> dict[str, str]:
    """Label and caption of the button that stops every idle safe group (P4, RF-24)."""
    ram = snapshot.reclaimable_now.ram
    groups = _safe_idle_groups(snapshot=snapshot)
    if ram <= 0 or not groups:
        return {"safe_label": _(NOTHING_SAFE_LABEL), "safe_text": ""}
    # "lo usi" / "li usi": the singular and the plural form of the whole sentence.
    text = ngettext(
        "Ferma {names}: non lo usi e non perdi nulla.",
        "Ferma {names}: non li usi e non perdi nulla.",
        len(groups),
    )
    return {
        "safe_label": _("Libera {size} senza rischi").format(size=format_size(size=ram)),
        "safe_text": text.format(names=_names(groups=groups)),
    }
