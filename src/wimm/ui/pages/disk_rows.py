from collections.abc import Callable

from gi.repository import Adw, GLib, Gtk

from wimm.i18n import _
from wimm.model.enums import ActionKind
from wimm.ui.disk_model import DiskRowView, DiskSectionView, EmptyStateView, SectionActionView
from wimm.ui.format import button_label, cache_clean_all_label
from wimm.ui.pages.disk_item_rows import item_children
from wimm.ui.pages.disk_select import OwnerChecks, SelectionChecks
from wimm.ui.widgets import ACCESSIBLE_LABEL_ATTR, color_primary
from wimm.ui.widgets.risk_badge import make_risk_badge

SPINNER_SIZE = 16
# 0 = no cap: the path and the whole consequence wrap at 360 px, never ellipsized (S4).
SUBTITLE_LINES = 0

RowAction = Callable[[DiskRowView], None]
SectionAction = Callable[[ActionKind], None]
ACTIONS_COLUMNS = 3
ACTIONS_SPACING = 6
SUFFIX_SPACING = 6
WARNING_ICON = "dialog-warning-symbolic"
WARNING_CLASS = "wimm-warning"


def build_warning_row(*, text: str) -> Adw.ActionRow:
    """A notice as text (the icon is decoration), so it does not rely on colour."""
    row = Adw.ActionRow(title=text, use_markup=False, title_lines=3)
    icon = Gtk.Image(icon_name=WARNING_ICON)
    icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
    row.add_prefix(icon)
    row.add_css_class(WARNING_CLASS)
    return row


def build_empty_state_row(
    *, state: EmptyStateView, on_choose: Callable[[], None] | None, buttons: list[Gtk.Button]
) -> Adw.ActionRow:
    """Headline, one sentence and the primary action; no button when nothing can answer it."""
    row = Adw.ActionRow(
        title=state.title, subtitle=state.text, use_markup=False, title_lines=2, subtitle_lines=4
    )
    if on_choose is not None:
        button = Gtk.Button(label=state.action_label, valign=Gtk.Align.CENTER)
        button.add_css_class("suggested-action")
        button.connect("clicked", lambda *_a: on_choose())
        row.add_suffix(button)
        buttons.append(button)
    return row


def _build_suffix(*, row: DiskRowView) -> Gtk.Box:
    """Size and badge on one line, the button (added by the caller) under them.

    Side by side they crush the title to an ellipsis and push the row past the edge at 360 px.
    """
    suffix = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SUFFIX_SPACING)
    suffix.set_valign(Gtk.Align.CENTER)
    info = Gtk.Box(spacing=SUFFIX_SPACING, halign=Gtk.Align.END)
    # F11: on one baseline. Centred, the bold size and the small badge text (baselines 15 and
    # 14) gave the box one height without a width and another with one, and GTK warned per row.
    size = Gtk.Label(label=row.size_text, valign=Gtk.Align.BASELINE_CENTER)
    size.add_css_class("wimm-reclaim")
    info.append(size)
    if row.risk_text is not None and row.risk_style is not None:
        badge = make_risk_badge(text=row.risk_text, style=row.risk_style)
        badge.set_valign(Gtk.Align.BASELINE_CENTER)
        info.append(badge)
    suffix.append(info)
    return suffix


def row_subtitle(*, row: DiskRowView) -> str:
    """The path, and the consequence on its own line under it when the row has an action."""
    return f"{row.subtitle}\n{row.consequence}" if row.consequence else row.subtitle


def row_accessible_name(*, row: DiskRowView) -> str:
    """Title, path and consequence as one sentence run, so a screen reader reads the effect."""
    return ". ".join(part for part in (row.title, row.subtitle, row.consequence) if part)


def _action_label(*, row: DiskRowView, kind: ActionKind) -> str:
    """ "Pulisci tutta la cache" on a cache that lists items: the button is not per model (S9)."""
    if kind is ActionKind.CACHE_CLEAN and row.items:
        return cache_clean_all_label()
    return button_label(kind=kind)


def _plain_row(*, row: DiskRowView) -> Adw.ActionRow:
    return Adw.ActionRow(
        title=row.title,
        subtitle=row_subtitle(row=row),
        use_markup=False,
        title_lines=2,
        subtitle_lines=SUBTITLE_LINES,
        tooltip_text=row.title,
    )


def _expander_row(*, row: DiskRowView) -> Adw.ExpanderRow:
    return Adw.ExpanderRow(
        title=row.title,
        subtitle=row_subtitle(row=row),
        use_markup=False,
        title_lines=2,
        subtitle_lines=SUBTITLE_LINES,
        tooltip_text=row.title,
        expanded=False,
    )


def _make_widget(
    *,
    row: DiskRowView,
    on_action: RowAction | None,
    buttons: list[Gtk.Button] | None,
    checks: OwnerChecks | None,
) -> Adw.ActionRow | Adw.ExpanderRow:
    """An expander (collapsed) for a cache with items, a plain row for everything else."""
    if not row.items:
        return _plain_row(row=row)
    expander = _expander_row(row=row)
    sub_checks = None if checks is None else checks.children_of
    for child in item_children(
        row=row, on_action=on_action, buttons=buttons, make_check=sub_checks
    ):
        expander.add_row(child)
    return expander


def _add_action_button(
    *,
    suffix: Gtk.Box,
    row: DiskRowView,
    on_action: RowAction | None,
    buttons: list[Gtk.Button] | None,
) -> None:
    if on_action is None or row.action_kind is None or row.risk is None:
        return
    button = Gtk.Button(label=_action_label(row=row, kind=row.action_kind), halign=Gtk.Align.END)
    color_primary(button=button, risk=row.risk)
    button.connect("clicked", lambda *_a: on_action(row))
    suffix.append(button)
    if buttons is not None:
        buttons.append(button)


def build_disk_row(
    *,
    row: DiskRowView,
    on_action: RowAction | None = None,
    buttons: list[Gtk.Button] | None = None,
    checks: OwnerChecks | None = None,
) -> Adw.ActionRow | Adw.ExpanderRow:
    """One row: title, state, size, risk badge; an action button only when a callback is given.

    Markup is off, so names containing "&" or "<" show as typed. The action button is also
    appended to ``buttons`` so the caller can disable it while an action runs. A row with
    ``items`` is an Adw.ExpanderRow whose children are those items. With ``checks``, a row that
    can be selected gets its check box as prefix.
    """
    widget = _make_widget(row=row, on_action=on_action, buttons=buttons, checks=checks)
    check = None if checks is None else checks.make(row)
    if check is not None:
        widget.add_prefix(check)
    name = row_accessible_name(row=row)
    widget.update_property([Gtk.AccessibleProperty.LABEL], [name])
    setattr(widget, ACCESSIBLE_LABEL_ATTR, name)  # GTK 4.14 has no getter; see widgets/__init__
    suffix = _build_suffix(row=row)
    widget.add_suffix(suffix)
    _add_action_button(suffix=suffix, row=row, on_action=on_action, buttons=buttons)
    return widget


class SectionGroup:
    """An Adw.PreferencesGroup for one section, with a spinner in its header."""

    def __init__(
        self,
        *,
        key: str,
        on_action: RowAction | None,
        on_section: SectionAction | None = None,
        on_choose: Callable[[], None] | None = None,
    ) -> None:
        self.key = key
        self._on_choose = on_choose
        self.group = Adw.PreferencesGroup()
        self.spinner = Gtk.Spinner(width_request=SPINNER_SIZE, height_request=SPINNER_SIZE)
        self.spinner.update_property([Gtk.AccessibleProperty.LABEL], [_("Controllo in corso")])
        self.group.set_header_suffix(self.spinner)
        self._on_action, self._on_section = on_action, on_section
        self._busy = False
        self._buttons: list[Gtk.Button] = []
        self._children: list[Gtk.Widget] = []
        self._shown: DiskSectionView | None = None
        self._checks: OwnerChecks | None = None
        self.set_scanning(scanning=False)

    def bind_selection(self, *, checks: SelectionChecks) -> None:
        """Give the rows a check box each in the Seleziona mode (S16)."""
        self._checks = checks.owned(owner=self.key)

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
        text = "\n".join(t for t in (section.description, section.message) if t)
        self.group.set_description(GLib.markup_escape_text(text))
        for child in self._children:
            self.group.remove(child)
        self._buttons = []
        if self._checks is not None:
            self._checks.drop()
        self._children = self._build_children(section=section)
        for child in self._children:
            self.group.add(child)
        self.set_busy(busy=self._busy)

    def _build_children(self, *, section: DiskSectionView) -> list[Gtk.Widget]:
        children: list[Gtk.Widget] = (
            [self._actions_row(actions=section.actions)] if section.actions else []
        )
        children += [build_warning_row(text=text) for text in section.warnings]
        if section.empty_state is not None:
            children.append(
                build_empty_state_row(
                    state=section.empty_state, on_choose=self._on_choose, buttons=self._buttons
                )
            )
        children += [
            build_disk_row(
                row=r, on_action=self._on_action, buttons=self._buttons, checks=self._checks
            )
            for r in section.rows
        ]
        if section.more_text:
            children.append(Adw.ActionRow(title=section.more_text, use_markup=False))
        return children

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
