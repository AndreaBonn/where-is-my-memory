"""The "Programmi senza avvisi" section: user state, changed at once, never part of "Applica"."""

from typing import Any

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk

from wimm.model.enums import GroupId

TITLE = "Programmi senza avvisi"
DESCRIPTION = "Non ricevi avvisi per questi programmi. Il cambiamento vale subito."
EMPTY_TEXT = "Nessun programma senza avvisi"
UNIGNORE_LABEL = "Non ignorare più"
INACTIVE_TEXT = "non attivo ora"


class IgnoredGroups:
    """Lists the ignored groups of the current snapshot, each with its undo button."""

    def __init__(self, *, source: Any) -> None:
        self._source = source
        self.group = Adw.PreferencesGroup(title=TITLE, description=DESCRIPTION)
        self._rows: dict[GroupId, Adw.ActionRow] = {}
        self._empty = Adw.ActionRow(title=EMPTY_TEXT, use_markup=False)
        snapshot = source.snapshot()
        names = {g.id: g.name for g in (() if snapshot is None else snapshot.groups)}
        for group_id in sorted(source.ignored_group_ids(), key=lambda gid: names.get(gid, gid)):
            self._add_row(group_id=group_id, name=names.get(group_id))
        self._sync_empty()

    def _add_row(self, *, group_id: GroupId, name: str | None) -> None:
        # A group that left the snapshot (its processes ended) is still ignored: show its id.
        label = group_id if name is None else name
        row = Adw.ActionRow(title=label, use_markup=False)
        if name is None:
            row.set_subtitle(INACTIVE_TEXT)
        button = Gtk.Button(label=UNIGNORE_LABEL, valign=Gtk.Align.CENTER)
        button.update_property([Gtk.AccessibleProperty.LABEL], [f"{UNIGNORE_LABEL}: {label}"])
        button.connect("clicked", lambda *_a: self._unignore(group_id=group_id))
        row.add_suffix(button)
        self._rows[group_id] = row
        self.group.add(row)

    def _unignore(self, *, group_id: GroupId) -> None:
        self._source.set_ignored(group_id=group_id, ignored=False)
        self.group.remove(self._rows.pop(group_id))
        self._sync_empty()

    def _sync_empty(self) -> None:
        if self._rows and self._empty.get_parent() is not None:
            self.group.remove(self._empty)
        elif not self._rows and self._empty.get_parent() is None:
            self.group.add(self._empty)


def can_unignore(*, source: object) -> bool:
    """True when the source can change the ignored state of a group."""
    return all(callable(getattr(source, n, None)) for n in ("set_ignored", "ignored_group_ids"))
