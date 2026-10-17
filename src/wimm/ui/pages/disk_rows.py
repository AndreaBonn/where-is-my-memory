from collections.abc import Callable

from gi.repository import Adw, GLib, Gtk

from wimm.model.enums import ActionKind
from wimm.ui.disk_view import DiskRowView, DiskSectionView, SectionActionView
from wimm.ui.format import button_label
from wimm.ui.widgets.risk_badge import make_risk_badge

SPINNER_SIZE = 16

RowAction = Callable[[DiskRowView], None]
SectionAction = Callable[[ActionKind], None]
ACTIONS_COLUMNS = 3
ACTIONS_SPACING = 6
SUFFIX_SPACING = 6


def _build_suffix(*, row: DiskRowView) -> Gtk.Box:
    """Size and badge on one line, the button (added by the caller) under them.

    Side by side they crush the title to an ellipsis and push the row past the edge at 360 px.
    """
    suffix = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SUFFIX_SPACING)
    suffix.set_valign(Gtk.Align.CENTER)
    info = Gtk.Box(spacing=SUFFIX_SPACING, halign=Gtk.Align.END)
    size = Gtk.Label(label=row.size_text, valign=Gtk.Align.CENTER)
    size.add_css_class("wimm-reclaim")
    info.append(size)
    if row.risk_text is not None and row.risk_style is not None:
        info.append(make_risk_badge(text=row.risk_text, style=row.risk_style))
    suffix.append(info)
    return suffix


def build_disk_row(
    *, row: DiskRowView, on_action: RowAction | None = None, buttons: list[Gtk.Button] | None = None
) -> Adw.ActionRow:
    """One row: title, state, size, risk badge; an action button only when a callback is given.

    Markup is off, so names containing "&" or "<" show as typed. The action button is also
    appended to ``buttons`` so the caller can disable it while an action runs.
    """
    widget = Adw.ActionRow(
        title=row.title,
        subtitle=row.subtitle,
        use_markup=False,
        title_lines=1,
        subtitle_lines=1,
        tooltip_text=row.title,
    )
    suffix = _build_suffix(row=row)
    widget.add_suffix(suffix)
    if on_action is not None and row.action_kind is not None and row.risk is not None:
        button = Gtk.Button(
            label=button_label(kind=row.action_kind, risk=row.risk), halign=Gtk.Align.END
        )
        button.connect("clicked", lambda *_a: on_action(row))
        suffix.append(button)
        if buttons is not None:
            buttons.append(button)
    return widget


class SectionGroup:
    """An Adw.PreferencesGroup for one section, with a spinner in its header."""

    def __init__(
        self, *, key: str, on_action: RowAction | None, on_section: SectionAction | None = None
    ) -> None:
        self.key = key
        self.group = Adw.PreferencesGroup()
        self.spinner = Gtk.Spinner(width_request=SPINNER_SIZE, height_request=SPINNER_SIZE)
        self.spinner.update_property([Gtk.AccessibleProperty.LABEL], ["Scansione in corso"])
        self.group.set_header_suffix(self.spinner)
        self._on_action, self._on_section = on_action, on_section
        self._busy = False
        self._buttons: list[Gtk.Button] = []
        self._children: list[Gtk.Widget] = []
        self._shown: DiskSectionView | None = None
        self.set_scanning(scanning=False)

    @property
    def row_count(self) -> int:
        """Rows listed, without the counter line."""
        return len(self._shown.rows) if self._shown else 0

    @property
    def more_label(self) -> str | None:
        """The "e altre N" text currently shown."""
        return self._shown.more_text if self._shown else None

    def set_scanning(self, *, scanning: bool) -> None:
        """Show or hide the section spinner; the rows stay as they are."""
        self.spinner.set_spinning(scanning)
        self.spinner.set_visible(scanning)

    def update(self, *, section: DiskSectionView) -> None:
        """Rebuild the rows when the section changed."""
        if section == self._shown:
            return
        self._shown = section
        self.group.set_title(section.title)
        # The description is markup and the message can carry a raw Docker error.
        self.group.set_description(GLib.markup_escape_text(section.message or ""))
        for child in self._children:
            self.group.remove(child)
        self._buttons = []
        self._children = [self._actions_row(actions=section.actions)] if section.actions else []
        self._children += [
            build_disk_row(row=r, on_action=self._on_action, buttons=self._buttons)
            for r in section.rows
        ]
        if section.more_text:
            self._children.append(Adw.ActionRow(title=section.more_text, use_markup=False))
        for child in self._children:
            self.group.add(child)
        self.set_busy(busy=self._busy)

    def set_busy(self, *, busy: bool) -> None:
        """Disable the section buttons while an action runs, like the overview does."""
        self._busy = busy
        for button in self._buttons:
            button.set_sensitive(not busy)

    def _actions_row(self, *, actions: tuple[SectionActionView, ...]) -> Adw.PreferencesRow:
        """The mass-action buttons in a flow box, so they wrap instead of crushing at 360 px."""
        flow = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            max_children_per_line=ACTIONS_COLUMNS,
            column_spacing=ACTIONS_SPACING,
            row_spacing=ACTIONS_SPACING,
            homogeneous=False,
        )
        for action in actions:
            button = Gtk.Button(label=action.label)
            button.connect("clicked", lambda *_a, kind=action.kind: self._start_section(kind=kind))
            flow.append(Gtk.FlowBoxChild(child=button, focusable=False))
            self._buttons.append(button)
        row = Adw.PreferencesRow(child=flow, activatable=False)
        for side in ("top", "bottom", "start", "end"):
            getattr(flow, f"set_margin_{side}")(ACTIONS_SPACING)
        return row

    def _start_section(self, *, kind: ActionKind) -> None:
        if self._on_section is not None:
            self._on_section(kind)
