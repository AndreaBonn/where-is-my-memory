"""P5/P6: two plain choices first, the narrowing filters behind "Altri filtri"."""

from collections.abc import Callable

from gi.repository import Gtk

from wimm.i18n import N_, _
from wimm.model.enums import Category, Protection, Risk, protection_of
from wimm.ui.format import CATEGORY_LABELS, RISK_TEXT
from wimm.ui.views import RowFilters

SECTION_SPACING = 8
LINE_SPACING = 2
SEARCH_PLACEHOLDER = N_("Cerca…")
SEARCH_LABEL = N_("Cerca tra i programmi")
FILTER_IDLE = N_("Da liberare")
FILTER_ALL = N_("Tutto")
MORE_MENU = N_("Altri filtri")
CATEGORY_TITLE = N_("Tipo di programma")
RISK_TITLE = N_("Rischio")
FILTERABLE_CATEGORIES = tuple(
    category for category in Category if protection_of(category=category) is Protection.ACTIONABLE
)


def _heading(*, text: str) -> Gtk.Label:
    label = Gtk.Label(label=text, xalign=0)
    label.add_css_class("heading")
    return label


def _counted(*, title: str, count: int | None) -> str:
    return title if count is None else f"{title} ({count})"


class FilterBar(Gtk.Box):
    """ "Da liberare" (the default) or "Tutto", "Altri filtri" and the search entry."""

    def __init__(self, *, on_changed: Callable[[RowFilters], None]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=SECTION_SPACING)
        self._on_changed = on_changed
        self._muted = False
        self._reported: RowFilters | None = None
        self._idle = Gtk.ToggleButton(label=_(FILTER_IDLE), active=True)
        self._all = Gtk.ToggleButton(label=_(FILTER_ALL), group=self._idle)
        self._categories: dict[Category, Gtk.CheckButton] = {}
        self._risks: dict[Risk, Gtk.CheckButton] = {}
        self._more = self._build_more()
        self.search = Gtk.SearchEntry(placeholder_text=_(SEARCH_PLACEHOLDER), hexpand=True)
        self.search.update_property([Gtk.AccessibleProperty.LABEL], [_(SEARCH_LABEL)])
        for toggle in (self._all, self._idle):
            toggle.connect("toggled", self._changed)
        self.search.connect("search-changed", self._changed)
        self.append(self._build_buttons())
        self.append(self.search)

    def _build_buttons(self) -> Gtk.Box:
        toggles = Gtk.Box()
        toggles.add_css_class("linked")
        toggles.append(self._idle)
        toggles.append(self._all)
        row = Gtk.Box(spacing=SECTION_SPACING)
        row.append(toggles)
        row.append(self._more)
        return row

    def _build_more(self) -> Gtk.MenuButton:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=LINE_SPACING)
        box.append(_heading(text=_(CATEGORY_TITLE)))
        self._add_checks(
            box=box,
            choices=[(c, _(CATEGORY_LABELS[c])) for c in FILTERABLE_CATEGORIES],
            store=self._categories,
        )
        box.append(_heading(text=_(RISK_TITLE)))
        self._add_checks(box=box, choices=[(r, _(RISK_TEXT[r])) for r in Risk], store=self._risks)
        button = Gtk.MenuButton(label=_(MORE_MENU), popover=Gtk.Popover(child=box))
        button.set_name(MORE_MENU)
        return button

    def _add_checks[K](
        self, *, box: Gtk.Box, choices: list[tuple[K, str]], store: dict[K, Gtk.CheckButton]
    ) -> None:
        for key, text in choices:
            check = Gtk.CheckButton(label=text)
            check.connect("toggled", self._changed)
            store[key] = check
            box.append(check)

    def set_counts(self, *, idle: int, total: int) -> None:
        """Show how many programs each choice lists: "Da liberare (4)", "Tutto (6)"."""
        self._idle.set_label(_counted(title=_(FILTER_IDLE), count=idle))
        self._all.set_label(_counted(title=_(FILTER_ALL), count=total))

    @property
    def filters(self) -> RowFilters:
        """Current filter state."""
        return RowFilters(
            only_idle=self._idle.get_active(),
            categories=frozenset(c for c, check in self._categories.items() if check.get_active()),
            risks=frozenset(r for r, check in self._risks.items() if check.get_active()),
            query=self.search.get_text(),
        )

    def reset(self) -> None:
        """Show everything (to reveal a group a filter hid) and notify once."""
        self._muted = True
        self._all.set_active(True)
        self.search.set_text("")
        for check in (*self._categories.values(), *self._risks.values()):
            check.set_active(False)
        self._muted = False
        self._changed()

    def _changed(self, *_args: object) -> None:
        if self._muted:
            return
        filters = self.filters
        active = len(filters.categories) + len(filters.risks)
        self._more.set_label(_counted(title=_(MORE_MENU), count=active or None))
        # A radio switch toggles two buttons and a cleared search reports late: one
        # notification per real change, so the page does not render twice.
        if filters == self._reported:
            return
        self._reported = filters
        self._on_changed(filters)
