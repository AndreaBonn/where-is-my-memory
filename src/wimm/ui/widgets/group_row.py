import logging
from collections.abc import Callable

from gi.repository import Adw, Gio, Gtk

from wimm.ui.views import GroupRow, MemberRow

from . import ACTIONS_UNAVAILABLE_TOOLTIP, NARROW_CLASS, name_icon_button
from .context_menu import (
    MENU_TOOLTIP,
    MenuTarget,
    attach_right_click,
    install_context_actions,
    make_context_button,
)
from .group_controls import GroupControlHandlers, GroupControls
from .risk_badge import make_risk_badge, update_risk_badge

LOGGER = logging.getLogger(__name__)
TITLE_LINES = 1
SUBTITLE_LINES = 3
MEMBER_SUBTITLE_LINES = 8
SUFFIX_SPACING = 8
PRIMARY_ACTION_NAME = "primary-action"
BUSY_LABEL = "In corso…"
RECLAIMABLE_TOOLTIP = "Memoria liberabile"
IGNORED_TEXT = "senza avvisi"
LINE_SEPARATOR = "\n"
FIELD_SEPARATOR = " · "


def member_subtitle(*, member: MemberRow) -> str:
    """Return the detail lines of a member: ids, command, working directory, mounts."""
    head = [member.key if member.kind == "container" else f"PID {member.key}"]
    if member.started:
        head.append(f"avvio {member.started}")
    head += [member.memory, member.activity]
    lines = [FIELD_SEPARATOR.join(head)]
    if member.image:
        lines.append(f"immagine {member.image}" + (f" ({member.state})" if member.state else ""))
    if member.command:
        lines.append(f"comando: {member.command}")
    if member.cwd:
        lines.append(f"cartella: {member.cwd}")
    if member.ports:
        lines.append(f"porte: {member.ports}")
    lines += (f"mount {mount}" for mount in member.mounts)
    return LINE_SEPARATOR.join(lines)


def target_of(*, member: MemberRow) -> MenuTarget:
    """Menu target for a member: PID only for processes."""
    pid = member.key if member.kind == "process" else None
    return MenuTarget(command=member.command, pid=pid, cwd=member.cwd)


def group_target(*, row: GroupRow) -> MenuTarget:
    """Menu target of a group: its first process member (a container group has none)."""
    for member in row.members:
        if member.kind == "process":
            return target_of(member=member)
    return MenuTarget(command=None, pid=None, cwd=None)


class _MemberEntry:
    """The widgets of one member, updated in place so an open menu and the focus survive."""

    def __init__(self, *, member: MemberRow) -> None:
        self.member = member
        self.widget = Adw.ActionRow(
            title=member.name,
            subtitle=member_subtitle(member=member),
            use_markup=False,
            title_lines=TITLE_LINES,
            subtitle_lines=MEMBER_SUBTITLE_LINES,
        )
        self._button = make_context_button(title=member.name)
        self.widget.add_suffix(self._button)
        install_context_actions(owner=self.widget, target=target_of(member=member))
        attach_right_click(widget=self.widget, button=self._button)

    def update(self, *, member: MemberRow) -> None:
        """Apply ``member``; an identical member costs nothing."""
        old, self.member = self.member, member
        if old == member:
            return
        if old.name != member.name:
            self.widget.set_title(member.name)
            name_icon_button(button=self._button, label=f"{MENU_TOOLTIP}: {member.name}")
        self.widget.set_subtitle(member_subtitle(member=member))
        if target_of(member=old) != target_of(member=member):
            install_context_actions(owner=self.widget, target=target_of(member=member))


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
        self.context_actions: Gio.SimpleActionGroup
        self._row: GroupRow | None = None
        self._info: Adw.ActionRow | None = None
        self._entries: dict[tuple[str, str], _MemberEntry] = {}
        self._members_wanted = False
        self._action: Gtk.Button | None = None
        self._busy = False
        self._build_suffix(row=row)
        attach_right_click(widget=self, button=self._menu)
        self.connect("notify::expanded", self._on_expanded)
        self.update(row=row)

    def _build_suffix(self, *, row: GroupRow) -> None:
        self._reclaim = Gtk.Label(valign=Gtk.Align.CENTER)
        self._reclaim.add_css_class("wimm-reclaim")
        self._reclaim.set_tooltip_text(RECLAIMABLE_TOOLTIP)
        self._badge = make_risk_badge(text=row.risk_text, style=row.risk_style)
        self._menu = make_context_button(title=row.title)
        self._suffix = Gtk.Box(spacing=SUFFIX_SPACING, valign=Gtk.Align.CENTER)
        for child in (self._reclaim, self._badge, self._menu):
            self._suffix.append(child)
        self.add_suffix(self._suffix)

    def update(self, *, row: GroupRow) -> None:
        """Bring the widget in line with ``row``; identical rows cost nothing."""
        old, self._row = self._row, row
        if old == row:
            return
        self.set_title(row.title)
        self.set_subtitle(_subtitle(row=row))
        self.set_tooltip_text(row.explanation)
        self._reclaim.set_label(row.reclaimable)
        update_risk_badge(badge=self._badge, text=row.risk_text, style=row.risk_style)
        if old is None or old.primary_action != row.primary_action:
            self._sync_action(row=row)
        self.context_actions = install_context_actions(owner=self, target=group_target(row=row))
        if self._members_wanted:
            self._sync_members(row=row)

    def set_narrow(self, *, narrow: bool) -> None:
        """Hide the secondary column (reclaimable amount) on narrow windows."""
        self._reclaim.set_visible(not narrow)
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
        self._info.set_subtitle(row.explanation)
        if self._controls is not None:
            self._controls.update(ignored=row.ignored)
        for key, member in zip(keys, row.members, strict=True):
            self._entries[key].update(member=member)

    def _rebuild_members(self, *, row: GroupRow, keys: list[tuple[str, str]]) -> None:
        """New member set: replace the member rows, keep the info row and the controls.

        Rebuilding the controls would close an open "Silenzia" menu at every process
        that starts or ends in the group.
        """
        for entry in self._entries.values():
            self.remove(entry.widget)
        if self._info is None or self._controls is None:
            self._add_header(row=row)
        else:
            self._info.set_title(_info_title(row=row))
            self._info.set_subtitle(row.explanation)
            self._controls.update(ignored=row.ignored)
        self._entries = {
            key: _MemberEntry(member=member) for key, member in zip(keys, row.members, strict=True)
        }
        for entry in self._entries.values():
            self.add_row(entry.widget)

    def _add_header(self, *, row: GroupRow) -> None:
        self._info = Adw.ActionRow(
            title=_info_title(row=row),
            subtitle=row.explanation,
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


def _subtitle(*, row: GroupRow) -> str:
    first = [row.subtitle]
    if row.ignored:
        first.append(IGNORED_TEXT)
    if row.snoozed_text:
        first.append(row.snoozed_text)
    return LINE_SEPARATOR.join([FIELD_SEPARATOR.join(first), row.detail])
