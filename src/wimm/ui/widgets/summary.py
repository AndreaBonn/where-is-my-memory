from collections.abc import Callable

from gi.repository import Gtk

from wimm.model.enums import ActionKind, Category, Protection, Risk, protection_of
from wimm.ui.format import ACTION_LABELS, CATEGORY_LABELS, RISK_TEXT
from wimm.ui.views import RowFilters, SummaryView

from . import ACTIONS_UNAVAILABLE_TOOLTIP
from .memory_bar import MemoryBar

MARGIN = 12
SECTION_SPACING = 8
STATUS_COLUMNS = 2
STATUS_COLUMN_SPACING = 12
FILTER_COLUMNS = 3
FILTER_COLUMN_SPACING = 8
FILTER_ROW_SPACING = 6
LINE_SPACING = 2
SEARCH_PLACEHOLDER = "Cerca…"
SEARCH_LABEL = "Cerca tra i gruppi"
FILTER_ALL = "Tutti"
FILTER_IDLE = "Inattivi"
CATEGORY_MENU = "Categoria"
RISK_MENU = "Rischio"
FILTERABLE_CATEGORIES = tuple(
    category for category in Category if protection_of(category=category) is Protection.ACTIONABLE
)


def _section_title(*, text: str) -> Gtk.Label:
    label = Gtk.Label(label=text, xalign=0)
    label.add_css_class("heading")
    return label


def _detail_label() -> Gtk.Label:
    return Gtk.Label(xalign=0, wrap=True, selectable=False)


class SummaryPanel(Gtk.Box):
    """RAM bar, disk usage, reclaimable totals and the (phase 3) stop-all button."""

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=SECTION_SPACING)
        self._ram_text = _detail_label()
        self._bar = MemoryBar()
        self._note = _detail_label()
        self._note.add_css_class("caption")
        self._note.add_css_class("dim-label")
        self._disk_title = _section_title(text="Disco")
        self._disk_text = _detail_label()
        self._disk_bar = Gtk.ProgressBar()
        self._reclaim = _detail_label()
        self._reclaim.add_css_class("wimm-reclaim")
        self._stop_all = Gtk.Button(label=ACTION_LABELS[ActionKind.STOP_ALL_IDLE_SAFE])
        self._stop_all.set_sensitive(False)
        self._stop_all.set_tooltip_text(ACTIONS_UNAVAILABLE_TOOLTIP)
        self._stop_all.set_name("stop-all-idle")
        for widget in (
            _section_title(text="RAM"),
            self._ram_text,
            self._bar,
            self._note,
            self._disk_title,
            self._disk_text,
            self._disk_bar,
            self._build_reclaim_row(),
        ):
            self.append(widget)

    def _build_reclaim_row(self) -> Gtk.FlowBox:
        row = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            max_children_per_line=STATUS_COLUMNS,
            homogeneous=False,
            column_spacing=STATUS_COLUMN_SPACING,
        )
        row.append(self._reclaim)
        row.append(self._stop_all)
        return row

    def update(self, *, view: SummaryView) -> None:
        """Show a new SummaryView."""
        self._ram_text.set_label(
            f"{view.ram_used} / {view.ram_total} · disponibile {view.ram_available}"
            f" · swap {view.swap_used} / {view.swap_total} · pressione {view.pressure_text}"
        )
        self._bar.update(segments=view.segments)
        self._note.set_label(view.kernel_cache_note)
        self._disk_title.set_label(f"Disco {view.disk_mount}")
        self._disk_text.set_label(f"{view.disk_used} / {view.disk_total} · liberi {view.disk_free}")
        self._disk_bar.set_fraction(view.disk_fraction)
        self._disk_bar.update_property(
            [Gtk.AccessibleProperty.LABEL],
            [f"Uso del disco {view.disk_mount}: {view.disk_used} su {view.disk_total}"],
        )
        self._reclaim.set_label(
            f"Recuperabile ora: {view.reclaimable_ram} di RAM · {view.reclaimable_disk} di disco"
        )


class FilterBar(Gtk.Box):
    """All/idle toggle, category and risk check popovers, and the search entry."""

    def __init__(self, *, on_changed: Callable[[RowFilters], None]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=SECTION_SPACING)
        self._on_changed = on_changed
        self._muted = False
        self._all = Gtk.ToggleButton(label=FILTER_ALL, active=True)
        self._idle = Gtk.ToggleButton(label=FILTER_IDLE, group=self._all)
        self._categories: dict[Category, Gtk.CheckButton] = {}
        self._risks: dict[Risk, Gtk.CheckButton] = {}
        self._category_menu = self._check_menu(
            title=CATEGORY_MENU,
            choices=[(c, CATEGORY_LABELS[c]) for c in FILTERABLE_CATEGORIES],
            store=self._categories,
        )
        self._risk_menu = self._check_menu(
            title=RISK_MENU,
            choices=[(r, RISK_TEXT[r]) for r in Risk],
            store=self._risks,
        )
        self.search = Gtk.SearchEntry(placeholder_text=SEARCH_PLACEHOLDER, hexpand=True)
        self.search.update_property([Gtk.AccessibleProperty.LABEL], [SEARCH_LABEL])
        self._all.connect("toggled", self._changed)
        self._idle.connect("toggled", self._changed)
        self.search.connect("search-changed", self._changed)
        self.append(self._build_buttons())
        self.append(self.search)

    def _build_buttons(self) -> Gtk.FlowBox:
        toggles = Gtk.Box()
        toggles.add_css_class("linked")
        toggles.append(self._all)
        toggles.append(self._idle)
        flow = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            max_children_per_line=FILTER_COLUMNS,
            homogeneous=False,
            column_spacing=FILTER_COLUMN_SPACING,
            row_spacing=FILTER_ROW_SPACING,
        )
        for widget in (toggles, self._category_menu, self._risk_menu):
            flow.append(widget)
        return flow

    def _check_menu[K](
        self, *, title: str, choices: list[tuple[K, str]], store: dict[K, Gtk.CheckButton]
    ) -> Gtk.MenuButton:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=LINE_SPACING)
        for key, text in choices:
            check = Gtk.CheckButton(label=text)
            check.connect("toggled", self._changed)
            store[key] = check
            box.append(check)
        button = Gtk.MenuButton(label=title, popover=Gtk.Popover(child=box))
        button.set_name(title)
        return button

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
        """Clear every filter and notify once."""
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
        self._category_menu.set_label(
            _menu_label(title=CATEGORY_MENU, count=len(filters.categories))
        )
        self._risk_menu.set_label(_menu_label(title=RISK_MENU, count=len(filters.risks)))
        self._on_changed(filters)


def _menu_label(*, title: str, count: int) -> str:
    return f"{title} ({count})" if count else title
