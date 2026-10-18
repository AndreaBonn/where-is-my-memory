"""The "Programmi senza avvisi" section: user state, changed at once, never part of "Applica"."""

from typing import Any

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk

from wimm.i18n import N_, _
from wimm.model.enums import GroupId

TITLE = N_("Programmi senza avvisi")
DESCRIPTION = N_("Non ricevi avvisi per questi programmi. Il cambiamento vale subito.")
EMPTY_TEXT = N_("Nessun programma senza avvisi")
UNIGNORE_LABEL = N_("Non ignorare più")
INACTIVE_TEXT = N_("non attivo ora")


class IgnoredGroups:
    """Lists the ignored groups of the current snapshot, each with its undo button."""

    def __init__(self, *, source: Any) -> None:
        self._source = source
        self.group = Adw.PreferencesGroup(title=_(TITLE), description=_(DESCRIPTION))
        self._rows: dict[GroupId, Adw.ActionRow] = {}
        self._empty = Adw.ActionRow(title=_(EMPTY_TEXT), use_markup=False)
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
            row.set_subtitle(_(INACTIVE_TEXT))
        unignore = _(UNIGNORE_LABEL)
        button = Gtk.Button(label=unignore, valign=Gtk.Align.CENTER)
        button.update_property([Gtk.AccessibleProperty.LABEL], [f"{unignore}: {label}"])
        button.connect("clicked", lambda *_a: self._unignore(group_id=group_id))
        row.add_suffix(button)
        self._rows[group_id] = row
        self.group.add(row)

    def _unignore(self, *, group_id: GroupId) -> None:
        self._source.set_ignored(group_id=group_id, ignored=False)
        self.group.remove(self._rows.pop(group_id))
        self._sync_empty()

    def _sync_empty(self) -> None:
        if not self._rows:
            self.group.add(self._empty)


def can_unignore(*, source: object) -> bool:
    """True when the source can change the ignored state of a group."""
    return all(callable(getattr(source, n, None)) for n in ("set_ignored", "ignored_group_ids"))
