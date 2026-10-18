import zlib
from datetime import datetime

from wimm.i18n import N_, _
from wimm.model.enums import ActivityState, Pressure, Protection
from wimm.model.snapshot import Group, Snapshot
from wimm.tray.dbus_menu import MenuItem
from wimm.tray.status_notifier import ICON_NORMAL as ICON_NORMAL
from wimm.ui.format import format_round_size, format_size

ICON_WARNING = "wimm-warning"
ICON_CRITICAL = "wimm-critical"

CALLBACK_OPEN = "open"
CALLBACK_MUTE = "mute"
CALLBACK_QUIT = "quit"
GROUP_PREFIX = "group:"

LABEL_MIN_BYTES = 100_000_000
MAX_MENU_GROUPS = 5
FAILURES_BEFORE_ERROR = 3
PERCENT = 100

ERROR_TEXT = N_("Monitoraggio in errore: apri il pannello per i dettagli")
OPEN_TEXT = N_("Apri Where Is My Memory")
GROUPS_HEADER_TEXT = N_("Da liberare:")
MUTE_TEXT = N_("Silenzia notifiche per 1 h")
QUIT_TEXT = N_("Esci")

# Fixed dbusmenu ids: a click may arrive for the layout the user saw before a refresh,
# so an id must never move to another entry (the old "Silenzia" id must not become "Esci").
# Group ids derive from the group id, so they survive a reorder of the groups.
ERROR_ID = 1
RAM_ID = 2
DISK_ID = 3
MUTE_ID = 4
QUIT_ID = 5
OPEN_ID = 6
GROUPS_HEADER_ID = 7
GROUP_BASE_ID = 100
GROUP_ID_SPAN = 2**31 - GROUP_BASE_ID

Entry = tuple[int, str, bool, str]


def _group_item_id(*, group_id: str, taken: set[int]) -> int:
    """A dbusmenu id stable per group id; probes upward only on a (rare) clash in one menu."""
    item_id = GROUP_BASE_ID + zlib.crc32(group_id.encode()) % GROUP_ID_SPAN
    while item_id in taken:
        item_id = GROUP_BASE_ID + (item_id - GROUP_BASE_ID + 1) % GROUP_ID_SPAN
    return item_id


def _percent(*, part: int, total: int) -> int:
    return (2 * part * PERCENT + total) // (2 * total) if total else 0


def _ram_percent(*, snapshot: Snapshot) -> int:
    return _percent(part=snapshot.memory.used, total=snapshot.memory.total)


def _disk_free(*, snapshot: Snapshot) -> str:
    return _("{size} liberi").format(size=format_round_size(size=snapshot.disk.free))


def _disk_entry(*, snapshot: Snapshot) -> str:
    """Disk use, plus what can be freed without losing data (the `safe` ratings, Q-6)."""
    used = _percent(part=snapshot.disk.used, total=snapshot.disk.total)
    # xgettext: no-python-format
    text = _("Disco: {percent}% occupato").format(percent=used)
    safe = snapshot.reclaimable_now.disk
    if safe == 0:
        # Also the value before the first disk scan: "0 B" would read as a measured nothing.
        return text
    return _("{text} ({size} liberabili senza rischio)").format(
        text=text, size=format_size(size=safe)
    )


def tray_label(*, snapshot: Snapshot | None) -> str:
    """Short text beside the icon: the reclaimable RAM, nothing below 100 MB (RF-40)."""
    if snapshot is None or snapshot.reclaimable_now.ram < LABEL_MIN_BYTES:
        return ""
    return _("{size} da liberare").format(size=format_size(size=snapshot.reclaimable_now.ram))


def tray_tooltip(*, snapshot: Snapshot | None) -> str:
    """RAM and disk summary, for example ``Memoria usata 79%, disco: 28 GB liberi``."""
    if snapshot is None:
        return ""
    # xgettext: no-python-format
    return _("Memoria usata {percent}%, disco: {disk}").format(
        percent=_ram_percent(snapshot=snapshot), disk=_disk_free(snapshot=snapshot)
    )


def tray_icon(*, snapshot: Snapshot | None, consecutive_failures: int) -> str:
    """Icon name for the memory pressure; sampling errors raise it to at least warning."""
    pressure = Pressure.OK if snapshot is None else snapshot.pressure
    if pressure is Pressure.CRITICAL:
        return ICON_CRITICAL
    failing = consecutive_failures >= FAILURES_BEFORE_ERROR
    return ICON_WARNING if pressure is Pressure.WARNING or failing else ICON_NORMAL


def parse_group_callback(*, callback_id: str) -> str | None:
    """The group id carried by a ``group:<id>`` callback, or None for any other callback."""
    if not callback_id.startswith(GROUP_PREFIX):
        return None
    return callback_id.removeprefix(GROUP_PREFIX) or None


def _idle_groups(*, snapshot: Snapshot) -> list[Group]:
    idle = [
        group
        for group in snapshot.groups
        if group.protection is Protection.ACTIONABLE
        and group.activity.state is ActivityState.IDLE
        and not group.ignored
    ]
    idle.sort(key=lambda g: (-g.memory.reclaimable, -g.memory.used, g.name.casefold(), g.id))
    return idle[:MAX_MENU_GROUPS]


def _summary_entries(*, snapshot: Snapshot) -> list[Entry]:
    entries = [
        (
            RAM_ID,
            _("Memoria usata: {percent}%").format(percent=_ram_percent(snapshot=snapshot)),
            False,
            "",
        ),
        (DISK_ID, _disk_entry(snapshot=snapshot), False, ""),
    ]
    idle = _idle_groups(snapshot=snapshot)
    if idle:
        entries.append((GROUPS_HEADER_ID, _(GROUPS_HEADER_TEXT), False, ""))
    taken: set[int] = set()
    for group in idle:
        item_id = _group_item_id(group_id=group.id, taken=taken)
        taken.add(item_id)
        label = f"{group.name} ({format_size(size=group.memory.reclaimable)})"
        entries.append((item_id, label, True, f"{GROUP_PREFIX}{group.id}"))
    return entries


def _mute_entry(*, muted_until: datetime | None) -> Entry:
    if muted_until is None:
        return (MUTE_ID, _(MUTE_TEXT), True, CALLBACK_MUTE)
    until = muted_until.astimezone().strftime("%H:%M")
    return (MUTE_ID, _("Notifiche silenziate fino alle {until}").format(until=until), False, "")


def build_menu(
    *, snapshot: Snapshot | None, consecutive_failures: int, muted_until: datetime | None = None
) -> list[MenuItem]:
    """Entries of the right-click menu (RF-42), in order, each kind with its own id."""
    entries: list[Entry] = []
    if consecutive_failures >= FAILURES_BEFORE_ERROR:
        # The error entry already opens the panel: one way in is enough.
        entries.append((ERROR_ID, _(ERROR_TEXT), True, CALLBACK_OPEN))
    else:
        entries.append((OPEN_ID, _(OPEN_TEXT), True, CALLBACK_OPEN))
    if snapshot is not None:
        entries.extend(_summary_entries(snapshot=snapshot))
    entries.append(_mute_entry(muted_until=muted_until))
    entries.append((QUIT_ID, _(QUIT_TEXT), True, CALLBACK_QUIT))
    return [
        MenuItem(id=item_id, label=label, enabled=enabled, callback_id=callback_id)
        for item_id, label, enabled, callback_id in entries
    ]
