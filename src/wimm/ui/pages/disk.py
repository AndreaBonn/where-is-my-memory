import shutil
from collections.abc import Callable
from datetime import datetime

from gi.repository import Adw, Gtk

from wimm.core.cache_catalog import withheld_kinds
from wimm.i18n import N_, _
from wimm.model.disk import DiskReport
from wimm.model.enums import ActionKind
from wimm.ui.disk_model import ROOTS_FINE, DiskSectionView, RootsState
from wimm.ui.disk_texts import TIER_TITLES, disk_headline, safe_label
from wimm.ui.disk_view import build_disk_sections, last_scan_text
from wimm.ui.pages.disk_header import DiskHeader, tier_heading
from wimm.ui.pages.disk_rows import RowAction, SectionAction, SectionGroup

MAX_CONTENT_WIDTH = 800
PAGE_MARGIN = 12
WAITING_TITLE = N_("Nessun controllo ancora")
WAITING_TEXT = N_("Il primo controllo parte poco dopo l'avvio. Puoi avviarlo con Controlla ora.")
SCANNING_TITLE = N_("Controllo in corso…")
FAILED_WITH_REPORT = N_("Il controllo non è riuscito: l'elenco mostra l'ultimo risultato.")
FAILED_WITHOUT_REPORT = N_("Il controllo non è riuscito. Riprova con Controlla ora.")
STATE_WAITING = "waiting"
STATE_LIST = "list"


class DiskPage(Gtk.Box):
    """Disco: scan header plus one group per section; the last report stays while scanning."""

    def __init__(
        self,
        *,
        on_rescan: Callable[[], None],
        on_action: RowAction | None = None,
        on_section: SectionAction | None = None,
        on_choose_folder: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._on_rescan, self._on_action, self._on_section = on_rescan, on_action, on_section
        self._on_choose_folder = on_choose_folder
        self._busy = False
        self._scanning = False
        self._has_report = False
        self._groups: dict[str, SectionGroup] = {}
        self._headings: list[Gtk.Widget] = []
        self._header = DiskHeader(
            waiting=_(WAITING_TITLE),
            on_scan=self._start_scan,
            on_safe=None if on_section is None else lambda: on_section(ActionKind.DISK_FREE_SAFE),
        )
        self.append(self._header.widget)
        self._notice = Gtk.Label(xalign=0, wrap=True, visible=False)
        self._notice.add_css_class("wimm-warning")
        self.append(self._notice)
        self.append(self._build_stack())

    def _build_stack(self) -> Gtk.Stack:
        self._waiting = Adw.StatusPage(
            title=_(WAITING_TITLE), description=_(WAITING_TEXT), icon_name="drive-harddisk-symbolic"
        )
        self._stack = Gtk.Stack(vexpand=True)
        self._stack.add_named(self._waiting, STATE_WAITING)
        self._stack.add_named(self._build_list(), STATE_LIST)
        self._stack.set_visible_child_name(STATE_WAITING)
        return self._stack

    def _build_list(self) -> Gtk.ScrolledWindow:
        self._sections_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=PAGE_MARGIN)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        clamp = Adw.Clamp(maximum_size=MAX_CONTENT_WIDTH, child=self._sections_box)
        clamp.set_margin_top(PAGE_MARGIN)
        clamp.set_margin_bottom(PAGE_MARGIN)
        clamp.set_margin_start(PAGE_MARGIN)
        clamp.set_margin_end(PAGE_MARGIN)
        scroller.set_child(clamp)
        return scroller

    @property
    def is_scanning(self) -> bool:
        """True from the service's disk-scan-started until the report or the failure arrives."""
        return self._scanning

    @property
    def header_text(self) -> str:
        """The last-scan line."""
        return self._header.scan_text.get_label()

    @property
    def headline_text(self) -> str | None:
        """The "Puoi liberare fino a …" line, if shown."""
        headline = self._header.headline
        return headline.get_label() if headline.get_visible() else None

    @property
    def notice_text(self) -> str | None:
        """The non-blocking failure message, if shown."""
        return self._notice.get_label() if self._notice.get_visible() else None

    @property
    def sections(self) -> dict[str, SectionGroup]:
        """The section groups currently built, by key."""
        return self._groups

    @property
    def row_count(self) -> int:
        """Rows listed over all sections."""
        return sum(g.row_count for g in self._groups.values())

    def _start_scan(self) -> None:
        # The scan state follows the service: a request that starts nothing shows nothing.
        self._on_rescan()

    def begin_scan(self) -> None:
        """Mark a scan as running: spinners on, button off, rows untouched."""
        self._set_scanning(scanning=True)
        self._notice.set_visible(False)

    def _set_scanning(self, *, scanning: bool) -> None:
        self._scanning = scanning
        self._header.set_scanning(scanning=scanning)
        for group in self._groups.values():
            group.set_scanning(scanning=scanning)
        self._waiting.set_title(_(SCANNING_TITLE if scanning else WAITING_TITLE))

    def show_report(
        self,
        *,
        report: DiskReport | None,
        now: datetime,
        min_age_days: int,
        roots: RootsState = ROOTS_FINE,
    ) -> None:
        """Show a fresh report (or None before the first scan) and end the scan state."""
        self._has_report = report is not None
        self._notice.set_visible(False)
        sections = build_disk_sections(
            report=report,
            min_age_days=min_age_days,
            roots=roots,
            withheld=withheld_kinds(which=shutil.which),
        )
        self._header.fill(
            headline=disk_headline(sections=sections),
            scan_text=last_scan_text(report=report, now=now),
            safe_label=safe_label(sections=sections),
        )
        self._sync_groups(sections=sections)
        self._set_scanning(scanning=False)

    def set_busy(self, *, busy: bool) -> None:
        """Disable every action button while a confirmed action runs."""
        self._busy = busy
        self._header.set_busy(busy=busy)
        for group in self._groups.values():
            group.set_busy(busy=busy)

    def show_scan_failed(self) -> None:
        """Keep the last report and say, without blocking, that the scan failed."""
        self._set_scanning(scanning=False)
        self._notice.set_label(_(FAILED_WITH_REPORT if self._has_report else FAILED_WITHOUT_REPORT))
        self._notice.set_visible(True)

    def _sync_groups(self, *, sections: tuple[DiskSectionView, ...]) -> None:
        wanted = [s.key for s in sections]
        if wanted != list(self._groups):
            self._rebuild_boxes(sections=sections)
        for section in sections:
            self._groups[section.key].update(section=section)
        self._stack.set_visible_child_name(STATE_LIST if sections else STATE_WAITING)

    def _rebuild_boxes(self, *, sections: tuple[DiskSectionView, ...]) -> None:
        for widget in [*self._headings, *(g.group for g in self._groups.values())]:
            self._sections_box.remove(widget)
        self._headings = []
        self._groups = {
            s.key: SectionGroup(
                key=s.key,
                on_action=self._on_action,
                on_section=self._on_section,
                on_choose=self._on_choose_folder,
            )
            for s in sections
        }
        tier = None
        for section, group in zip(sections, self._groups.values(), strict=True):
            # The "Docker non disponibile" notice belongs to no risk tier: no title above it.
            if section.tier != tier and section.tier in TIER_TITLES:
                tier = section.tier
                heading = tier_heading(tier=tier)
                self._headings.append(heading)
                self._sections_box.append(heading)
            self._sections_box.append(group.group)
            group.set_busy(busy=self._busy)
