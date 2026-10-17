from collections.abc import Callable
from datetime import datetime

from gi.repository import Adw, Gtk

from wimm.model.disk import DiskReport
from wimm.ui.disk_view import DiskSectionView, build_disk_sections, last_scan_text
from wimm.ui.pages.disk_rows import RowAction, SectionAction, SectionGroup

MAX_CONTENT_WIDTH = 800
PAGE_MARGIN = 12
SCAN_LABEL = "Scansiona ora"
WAITING_TITLE = "Nessuna scansione ancora"
WAITING_TEXT = "La prima scansione parte poco dopo l'avvio. Puoi avviarla con Scansiona ora."
SCANNING_TITLE = "Scansione in corso…"
FAILED_WITH_REPORT = "La scansione non è riuscita: l'elenco mostra l'ultimo risultato."
FAILED_WITHOUT_REPORT = "La scansione non è riuscita. Riprova con Scansiona ora."
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
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._on_rescan, self._on_action, self._on_section = on_rescan, on_action, on_section
        self._busy = False
        self._scanning = False
        self._has_report = False
        self._groups: dict[str, SectionGroup] = {}
        self._build_header()
        self._notice = Gtk.Label(xalign=0, wrap=True, visible=False)
        self._notice.add_css_class("wimm-warning")
        self._waiting = Adw.StatusPage(
            title=WAITING_TITLE, description=WAITING_TEXT, icon_name="drive-harddisk-symbolic"
        )
        scroller = self._build_list()
        self._stack = Gtk.Stack(vexpand=True)
        self._stack.add_named(self._waiting, STATE_WAITING)
        self._stack.add_named(scroller, STATE_LIST)
        self.append(self._notice)
        self.append(self._stack)
        self._stack.set_visible_child_name(STATE_WAITING)

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

    def _build_header(self) -> None:
        self._scan_label = Gtk.Label(
            label=WAITING_TITLE, xalign=0, hexpand=True, wrap=True, valign=Gtk.Align.CENTER
        )
        self._scan_label.add_css_class("dim-label")
        self._spinner = Gtk.Spinner(visible=False)
        self._spinner.update_property([Gtk.AccessibleProperty.LABEL], ["Scansione in corso"])
        self._button = Gtk.Button(label=SCAN_LABEL, valign=Gtk.Align.CENTER)
        self._button.connect("clicked", lambda *_a: self._start_scan())
        header = Gtk.Box(spacing=PAGE_MARGIN)
        for widget in (self._scan_label, self._spinner, self._button):
            header.append(widget)
        # Same column as the sections, so the button sits over the list it rescans.
        clamp = Adw.Clamp(maximum_size=MAX_CONTENT_WIDTH, child=header, margin_top=PAGE_MARGIN)
        clamp.set_margin_start(PAGE_MARGIN)
        clamp.set_margin_end(PAGE_MARGIN)
        self.append(clamp)

    @property
    def is_scanning(self) -> bool:
        """True from the service's disk-scan-started until the report or the failure arrives."""
        return self._scanning

    @property
    def header_text(self) -> str:
        """The last-scan line."""
        return self._scan_label.get_label()

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
        self._spinner.set_visible(scanning)
        self._spinner.set_spinning(scanning)
        self._button.set_sensitive(not scanning)
        for group in self._groups.values():
            group.set_scanning(scanning=scanning)
        self._waiting.set_title(SCANNING_TITLE if scanning else WAITING_TITLE)

    def show_report(self, *, report: DiskReport | None, now: datetime, min_age_days: int) -> None:
        """Show a fresh report (or None before the first scan) and end the scan state."""
        self._has_report = report is not None
        self._notice.set_visible(False)
        self._scan_label.set_label(last_scan_text(report=report, now=now))
        self._sync_groups(sections=build_disk_sections(report=report, min_age_days=min_age_days))
        self._set_scanning(scanning=False)

    def set_busy(self, *, busy: bool) -> None:
        """Disable every action button while a confirmed action runs."""
        self._busy = busy
        for group in self._groups.values():
            group.set_busy(busy=busy)

    def show_scan_failed(self) -> None:
        """Keep the last report and say, without blocking, that the scan failed."""
        self._set_scanning(scanning=False)
        self._notice.set_label(FAILED_WITH_REPORT if self._has_report else FAILED_WITHOUT_REPORT)
        self._notice.set_visible(True)

    def _sync_groups(self, *, sections: tuple[DiskSectionView, ...]) -> None:
        wanted = [s.key for s in sections]
        if wanted != list(self._groups):
            self._rebuild_boxes(sections=sections)
        for section in sections:
            self._groups[section.key].update(section=section)
        self._stack.set_visible_child_name(STATE_LIST if sections else STATE_WAITING)

    def _rebuild_boxes(self, *, sections: tuple[DiskSectionView, ...]) -> None:
        for group in self._groups.values():
            self._sections_box.remove(group.group)
        self._groups = {
            s.key: SectionGroup(key=s.key, on_action=self._on_action, on_section=self._on_section)
            for s in sections
        }
        for group in self._groups.values():
            self._sections_box.append(group.group)
            group.set_busy(busy=self._busy)
