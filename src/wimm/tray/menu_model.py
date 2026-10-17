from datetime import datetime

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

ERROR_TEXT = "Monitoraggio in errore: apri il pannello per i dettagli"
OPEN_TEXT = "Apri Where Is My Memory"
GROUPS_HEADER_TEXT = "Da liberare:"
MUTE_TEXT = "Silenzia notifiche per 1 h"
QUIT_TEXT = "Esci"

# Fixed dbusmenu ids: a click may arrive for the layout the user saw before a refresh,
# so an id must never move to another entry (the old "Silenzia" id must not become "Esci").
ERROR_ID = 1
RAM_ID = 2
DISK_ID = 3
MUTE_ID = 4
QUIT_ID = 5
OPEN_ID = 6
GROUPS_HEADER_ID = 7
GROUP_BASE_ID = 100

Entry = tuple[int, str, bool, str]


def _percent(*, part: int, total: int) -> int:
    return (2 * part * PERCENT + total) // (2 * total) if total else 0


def _ram_percent(*, snapshot: Snapshot) -> int:
    return _percent(part=snapshot.memory.used, total=snapshot.memory.total)


def _disk_free(*, snapshot: Snapshot) -> str:
    return f"{format_round_size(size=snapshot.disk.free)} liberi"


def tray_label(*, snapshot: Snapshot | None) -> str:
    """Short text beside the icon: the reclaimable RAM, nothing below 100 MB (RF-40)."""
    if snapshot is None or snapshot.reclaimable_now.ram < LABEL_MIN_BYTES:
        return ""
    return f"{format_size(size=snapshot.reclaimable_now.ram)} da liberare"


def tray_tooltip(*, snapshot: Snapshot | None) -> str:
    """RAM and disk summary, for example ``Memoria usata 79%, disco: 28 GB liberi``."""
    if snapshot is None:
        return ""
    return (
        f"Memoria usata {_ram_percent(snapshot=snapshot)}%, disco: {_disk_free(snapshot=snapshot)}"
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
        (RAM_ID, f"Memoria usata: {_ram_percent(snapshot=snapshot)}%", False, ""),
        (DISK_ID, f"Disco: {_disk_free(snapshot=snapshot)}", False, ""),
    ]
    idle = _idle_groups(snapshot=snapshot)
    if idle:
        entries.append((GROUPS_HEADER_ID, GROUPS_HEADER_TEXT, False, ""))
    for slot, group in enumerate(idle):
        size = format_size(size=group.memory.reclaimable)
        label = f"{group.name} ({size})"
        entries.append((GROUP_BASE_ID + slot, label, True, f"{GROUP_PREFIX}{group.id}"))
    return entries


def _mute_entry(*, muted_until: datetime | None) -> Entry:
    if muted_until is None:
        return (MUTE_ID, MUTE_TEXT, True, CALLBACK_MUTE)
    until = muted_until.astimezone().strftime("%H:%M")
    return (MUTE_ID, f"Notifiche silenziate fino alle {until}", False, "")


def build_menu(
    *, snapshot: Snapshot | None, consecutive_failures: int, muted_until: datetime | None = None
) -> list[MenuItem]:
    """Entries of the right-click menu (RF-42), in order, each kind with its own id."""
    entries: list[Entry] = []
    if consecutive_failures >= FAILURES_BEFORE_ERROR:
        # The error entry already opens the panel: one way in is enough.
        entries.append((ERROR_ID, ERROR_TEXT, True, CALLBACK_OPEN))
    else:
        entries.append((OPEN_ID, OPEN_TEXT, True, CALLBACK_OPEN))
    if snapshot is not None:
        entries.extend(_summary_entries(snapshot=snapshot))
    entries.append(_mute_entry(muted_until=muted_until))
    entries.append((QUIT_ID, QUIT_TEXT, True, CALLBACK_QUIT))
    return [
        MenuItem(id=item_id, label=label, enabled=enabled, callback_id=callback_id)
        for item_id, label, enabled, callback_id in entries
    ]
