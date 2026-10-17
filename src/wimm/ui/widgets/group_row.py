import logging
from collections.abc import Callable

from gi.repository import Adw, Gtk

from wimm.ui.views import GroupRow, MemberRow

from . import ACTIONS_UNAVAILABLE_TOOLTIP, NARROW_CLASS
from .group_controls import GroupControlHandlers, GroupControls
from .member_row import MemberEntry
from .risk_badge import make_risk_badge, update_risk_badge

LOGGER = logging.getLogger(__name__)
TITLE_LINES = 1
SUBTITLE_LINES = 3
SUFFIX_SPACING = 8
NARROW_SUFFIX_SPACING = 4
PRIMARY_ACTION_NAME = "primary-action"
BUSY_LABEL = "In corso…"
RECLAIMABLE_TOOLTIP = "Memoria liberabile"
IGNORED_TEXT = "senza avvisi"
LINE_SEPARATOR = "\n"
FIELD_SEPARATOR = " · "


def _member_key(*, member: MemberRow) -> tuple[str, str]:
    return (member.kind, member.key)


class GroupRowWidget(Adw.ExpanderRow):
    """One group of the Panoramica; members are built when the row is first expanded."""

    def __init__(
        self,
        *,
        row: GroupRow,
        on_action: Callable[[GroupRow], None] | None = None,
        controls: GroupControlHandlers | None = None,
    ) -> None:
        super().__init__(
            use_markup=False,
            title_lines=TITLE_LINES,
            subtitle_lines=SUBTITLE_LINES,
        )
        self._on_action = on_action
        self._handlers = controls
        self._controls: GroupControls | None = None
        self.group_id = row.id
        self.sort_rank = 0
        self.is_idle = row.is_idle
        self._row: GroupRow | None = None
        self._info: Adw.ActionRow | None = None
        self._entries: dict[tuple[str, str], MemberEntry] = {}
        self._members_wanted = False
        self._action: Gtk.Button | None = None
        self._busy = False
        self._build_suffix(row=row)
        self.connect("notify::expanded", self._on_expanded)
        self.update(row=row)

    def _build_suffix(self, *, row: GroupRow) -> None:
        self._reclaim = Gtk.Label(valign=Gtk.Align.CENTER)
        self._reclaim.add_css_class("wimm-reclaim")
        self._reclaim.set_tooltip_text(RECLAIMABLE_TOOLTIP)
        self._badge = make_risk_badge(text=row.risk_text, style=row.risk_style)
        self._suffix = Gtk.Box(spacing=SUFFIX_SPACING, valign=Gtk.Align.CENTER)
        for child in (self._reclaim, self._badge):
            self._suffix.append(child)
        self.add_suffix(self._suffix)

    def update(self, *, row: GroupRow) -> None:
        """Bring the widget in line with ``row``; identical rows cost nothing."""
        old, self._row = self._row, row
        if old == row:
            return
        self.is_idle = row.is_idle
        self.set_title(row.title)
        self.set_subtitle(_subtitle(row=row))
        self.set_tooltip_text(row.explanation)
        self._reclaim.set_label(row.reclaimable)
        update_risk_badge(badge=self._badge, text=row.risk_text, style=row.risk_style)
        if old is None or old.primary_action != row.primary_action:
            self._sync_action(row=row)
        if self._members_wanted:
            self._sync_members(row=row)

    def set_narrow(self, *, narrow: bool) -> None:
        """P14: on narrow windows size, badge and button stack on the right."""
        vertical = Gtk.Orientation.VERTICAL if narrow else Gtk.Orientation.HORIZONTAL
        self._suffix.set_orientation(vertical)
        self._suffix.set_spacing(NARROW_SUFFIX_SPACING if narrow else SUFFIX_SPACING)
        self._suffix.set_halign(Gtk.Align.END if narrow else Gtk.Align.FILL)
        if narrow:
            self.add_css_class(NARROW_CLASS)
        else:
            self.remove_css_class(NARROW_CLASS)

    def _sync_action(self, *, row: GroupRow) -> None:
        if self._action is not None:
            self._suffix.remove(self._action)
            self._action = None
        if row.primary_action is None:
            return
        self._action = Gtk.Button(label=row.primary_action.label, valign=Gtk.Align.CENTER)
        self._action.set_name(PRIMARY_ACTION_NAME)
        if self._on_action is None:
            self._action.set_sensitive(False)
            self._action.set_tooltip_text(ACTIONS_UNAVAILABLE_TOOLTIP)
        else:
            self._action.connect("clicked", self._on_primary_clicked)
        self._suffix.insert_child_after(self._action, self._badge)
        self.set_busy(busy=self._busy)

    def set_busy(self, *, busy: bool) -> None:
        """Disable the primary button and say "In corso…" while an action runs."""
        self._busy = busy
        if self._action is None or self._row is None or self._row.primary_action is None:
            return
        self._action.set_sensitive(self._on_action is not None and not busy)
        self._action.set_label(BUSY_LABEL if busy else self._row.primary_action.label)

    def _on_primary_clicked(self, *_args: object) -> None:
        if self._on_action is not None and self._row is not None:
            self._on_action(self._row)

    def _on_expanded(self, *_args: object) -> None:
        self._members_wanted = self.get_expanded()
        if self._members_wanted and self._row is not None:
            self._sync_members(row=self._row)

    def _sync_members(self, *, row: GroupRow) -> None:
        """Update the member rows in place; rebuild only when the set of members changes."""
        keys = [_member_key(member=member) for member in row.members]
        if self._info is None or keys != list(self._entries):
            self._rebuild_members(row=row, keys=keys)
            return
        self._info.set_title(_info_title(row=row))
        self._info.set_subtitle(_info_subtitle(row=row))
        if self._controls is not None:
            self._controls.update(ignored=row.ignored)
        for key, member in zip(keys, row.members, strict=True):
            self._entries[key].update(member=member)

    def _rebuild_members(self, *, row: GroupRow, keys: list[tuple[str, str]]) -> None:
        """New member set: drop the members that left, add the new ones, keep the rest.

        Rebuilding the controls would close an open "Silenzia" menu at every process
        that starts or ends in the group.
        """
        kept = self._entries
        for key in [key for key in kept if key not in keys]:
            self.remove(kept.pop(key).widget)
        if self._info is None or self._controls is None:
            self._add_header(row=row)
        else:
            self._info.set_title(_info_title(row=row))
            self._info.set_subtitle(_info_subtitle(row=row))
            self._controls.update(ignored=row.ignored)
        # Members that stay are updated in place (focus, open menu and open details survive);
        # new ones are appended after them.
        self._entries = {}
        for key, member in zip(keys, row.members, strict=True):
            previous = kept.get(key)
            if previous is None:
                previous = MemberEntry(member=member)
                self.add_row(previous.widget)
            else:
                previous.update(member=member)
            self._entries[key] = previous

    def _add_header(self, *, row: GroupRow) -> None:
        self._info = Adw.ActionRow(
            title=_info_title(row=row),
            subtitle=_info_subtitle(row=row),
            use_markup=False,
            subtitle_lines=0,
        )
        self._controls = GroupControls(
            group_id=row.id, ignored=row.ignored, handlers=self._handlers
        )
        self.add_row(self._info)
        self.add_row(self._controls)


def _info_title(*, row: GroupRow) -> str:
    return f"Liberabile: {row.reclaimable} · in uso: {row.memory}"


def _info_subtitle(*, row: GroupRow) -> str:
    """What the group is, then the measure behind its state (P7 keeps it out of the row)."""
    return LINE_SEPARATOR.join(part for part in (row.explanation, row.technical) if part)


def _subtitle(*, row: GroupRow) -> str:
    first = [row.subtitle]
    if row.ignored:
        first.append(IGNORED_TEXT)
    if row.snoozed_text:
        first.append(row.snoozed_text)
    return LINE_SEPARATOR.join([FIELD_SEPARATOR.join(first), row.detail])
