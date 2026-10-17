from collections.abc import Callable

from gi.repository import Adw, GLib, Gtk

from wimm.ui.disk_view import DiskRowView, DiskSectionView
from wimm.ui.format import button_label
from wimm.ui.widgets.risk_badge import make_risk_badge

SPINNER_SIZE = 16

RowAction = Callable[[DiskRowView], None]


def build_disk_row(*, row: DiskRowView, on_action: RowAction | None = None) -> Adw.ActionRow:
    """One row: title, state, size, risk badge; an action button only when a callback is given.

    Markup is off, so names containing "&" or "<" show as typed.
    """
    widget = Adw.ActionRow(
        title=row.title,
        subtitle=row.subtitle,
        use_markup=False,
        title_lines=1,
        subtitle_lines=1,
        tooltip_text=row.title,
    )
    size = Gtk.Label(label=row.size_text, valign=Gtk.Align.CENTER)
    size.add_css_class("wimm-reclaim")
    widget.add_suffix(size)
    if row.risk_text is not None and row.risk_style is not None:
        widget.add_suffix(make_risk_badge(text=row.risk_text, style=row.risk_style))
    if on_action is not None and row.action_kind is not None and row.risk is not None:
        button = Gtk.Button(
            label=button_label(kind=row.action_kind, risk=row.risk), valign=Gtk.Align.CENTER
        )
        button.connect("clicked", lambda *_a: on_action(row))
        widget.add_suffix(button)
    return widget


class SectionGroup:
    """An Adw.PreferencesGroup for one section, with a spinner in its header."""

    def __init__(self, *, key: str, on_action: RowAction | None) -> None:
        self.key = key
        self.group = Adw.PreferencesGroup()
        self.spinner = Gtk.Spinner(width_request=SPINNER_SIZE, height_request=SPINNER_SIZE)
        self.spinner.update_property([Gtk.AccessibleProperty.LABEL], ["Scansione in corso"])
        self.group.set_header_suffix(self.spinner)
        self._on_action = on_action
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
        self._children = [build_disk_row(row=r, on_action=self._on_action) for r in section.rows]
        if section.more_text:
            self._children.append(Adw.ActionRow(title=section.more_text, use_markup=False))
        for child in self._children:
            self.group.add(child)
