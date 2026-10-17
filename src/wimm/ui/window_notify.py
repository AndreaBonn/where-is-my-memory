from typing import Any, cast

from gi.repository import Gio

from wimm.model.enums import GroupId
from wimm.ui.widgets.group_controls import GroupControlHandlers
from wimm.ui.window_shortcuts import ACTION_PREFERENCES

ACTION_NAME = "snooze-all"
ACTION_SNOOZE_ALL = f"win.{ACTION_NAME}"
SNOOZE_ALL_TEXT = "Silenzia 1 h"
SNOOZE_ALL_SECONDS = 3600
MUTED_TEXT = "Notifiche silenziate fino alle {until}"
MUTE_ENTRY_INDEX = 1


def can_snooze(*, source: object) -> bool:
    """True when the source silences notifications (the real service; test sources cannot)."""
    return all(callable(getattr(source, name, None)) for name in ("snooze", "set_ignored"))


def group_controls(*, source: object) -> GroupControlHandlers | None:
    """The Silenzia and Ignora handlers of the group rows, or None without the service."""
    if not can_snooze(source=source):
        return None
    service = cast(Any, source)
    return GroupControlHandlers(
        on_snooze=lambda gid, seconds: service.snooze(group_id=GroupId(gid), duration_s=seconds),
        on_ignore=lambda gid, ignored: service.set_ignored(group_id=GroupId(gid), ignored=ignored),
    )


class SnoozeAllEntry:
    """The "Silenzia 1 h" item of the window menu: starts the global mute and shows its end."""

    def __init__(self, *, source: object, menu: Gio.Menu) -> None:
        self._source, self._menu = source, menu
        self._label = SNOOZE_ALL_TEXT
        self.action = Gio.SimpleAction.new(ACTION_NAME, None)
        self.action.connect("activate", self._activate)
        self.sync()

    def sync(self) -> None:
        """Bring label and enabled state in line with the service's global mute."""
        enabled = callable(getattr(self._source, "snooze_all", None))
        until = getattr(self._source, "notifications_muted_until", None) if enabled else None
        label = SNOOZE_ALL_TEXT
        if until is not None:
            label = MUTED_TEXT.format(until=until.astimezone().strftime("%H:%M"))
        self.action.set_enabled(enabled and until is None)
        if label != self._label:
            self._label = label
            self._menu.remove(MUTE_ENTRY_INDEX)
            self._menu.insert(MUTE_ENTRY_INDEX, label, ACTION_SNOOZE_ALL)

    def _activate(self, *_args: object) -> None:
        cast(Any, self._source).snooze_all(duration_s=SNOOZE_ALL_SECONDS)
        self.sync()


def build_main_menu(*, source: object) -> tuple[Gio.Menu, SnoozeAllEntry]:
    """The window menu (Preferenze, Silenzia 1 h, Info, Esci) and the entry to keep in sync."""
    menu = Gio.Menu()
    menu.append("Preferenze", ACTION_PREFERENCES)
    menu.append(SNOOZE_ALL_TEXT, ACTION_SNOOZE_ALL)
    menu.append("Info", "win.about")
    menu.append("Esci", "app.quit")
    return menu, SnoozeAllEntry(source=source, menu=menu)
