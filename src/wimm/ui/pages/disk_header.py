"""The top of the Disco page (D1, D2, D7) and the titles of the risk tiers (D3)."""

from collections.abc import Callable

from gi.repository import Adw, Gtk

from wimm.i18n import N_, _
from wimm.ui.disk_texts import (
    ACTIONS_NOTE,
    SAFE_CAPTION,
    TIER_DESCRIPTIONS,
    TIER_TITLES,
    selected_label,
)

MAX_CONTENT_WIDTH = 800
PAGE_MARGIN = 12
HEADER_SPACING = 2
SCAN_LABEL = N_("Controlla ora")
SAFE_BUTTON_NAME = "disk-free-safe"
SCANNING_LABEL = N_("Controllo in corso")
SELECT_LABEL = N_("Seleziona")
SELECT_TOGGLE_NAME = "disk-select"
FREE_SELECTED_NAME = "disk-free-selected"


def _caption(*, text: str = "") -> Gtk.Label:
    label = Gtk.Label(label=text, xalign=0, wrap=True)
    label.add_css_class("caption")
    label.add_css_class("dim-label")
    return label


def tier_heading(*, tier: str) -> Gtk.Box:
    """The title and the one-line meaning of a risk tier, above its sections."""
    title = Gtk.Label(label=_(TIER_TITLES[tier]), xalign=0, wrap=True)
    title.add_css_class("title-4")
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=HEADER_SPACING)
    box.append(title)
    box.append(_caption(text=_(TIER_DESCRIPTIONS[tier])))
    return box


# Adw.Clamp is a final type: the header keeps one in `widget` instead of subclassing it.
class DiskHeader:
    """What the disk can free, when it was checked, and the one-click safe cleanup."""

    def __init__(
        self, *, waiting: str, on_scan: Callable[[], None], on_safe: Callable[[], None] | None
    ) -> None:
        self.widget = Adw.Clamp(maximum_size=MAX_CONTENT_WIDTH, margin_top=PAGE_MARGIN)
        self.widget.set_margin_start(PAGE_MARGIN)
        self.widget.set_margin_end(PAGE_MARGIN)
        self._build_texts(waiting=waiting)
        self.safe = Gtk.Button(halign=Gtk.Align.START, visible=False)
        self.safe.set_name(SAFE_BUTTON_NAME)
        self.safe.add_css_class("suggested-action")
        self._can_safe = on_safe is not None
        if on_safe is not None:
            self.safe.connect("clicked", lambda *_a: on_safe())
        self.safe_caption = _caption(text=_(SAFE_CAPTION))
        self._build_selection_widgets()
        self._busy = False
        self._ticked = 0
        self.spinner = Gtk.Spinner(visible=False)
        self.spinner.update_property([Gtk.AccessibleProperty.LABEL], [_(SCANNING_LABEL)])
        self.scan = Gtk.Button(label=_(SCAN_LABEL), valign=Gtk.Align.CENTER)
        self.scan.connect("clicked", lambda *_a: on_scan())
        self.widget.set_child(self._layout())

    def _build_texts(self, *, waiting: str) -> None:
        self.headline = Gtk.Label(xalign=0, wrap=True, visible=False)
        self.headline.add_css_class("title-3")
        self.review = Gtk.Label(xalign=0, wrap=True, visible=False)
        self.scan_text = Gtk.Label(label=waiting, xalign=0, wrap=True)
        self.scan_text.add_css_class("dim-label")

    def _build_selection_widgets(self) -> None:
        self.select_toggle = Gtk.ToggleButton(
            label=_(SELECT_LABEL), halign=Gtk.Align.START, visible=False
        )
        self.select_toggle.set_name(SELECT_TOGGLE_NAME)
        self.free_selected = Gtk.Button(halign=Gtk.Align.START, visible=False, sensitive=False)
        self.free_selected.set_name(FREE_SELECTED_NAME)
        self.free_selected.set_label(selected_label(count=0, total_bytes=0))

    def _layout(self) -> Gtk.Box:
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=HEADER_SPACING, hexpand=True)
        lines: list[Gtk.Widget] = [self.headline, self.review, self.scan_text, self.safe]
        lines += [self.safe_caption, self.select_toggle, self.free_selected]
        for line in [*lines, _caption(text=_(ACTIONS_NOTE))]:
            texts.append(line)
        header = Gtk.Box(spacing=PAGE_MARGIN)
        for part in (texts, self.spinner, self.scan):
            header.append(part)
        return header

    def fill(self, *, headline: str, review: str, scan_text: str, safe_label: str) -> None:
        """Fill the lines; an empty headline, review line or safe label hides its widget."""
        for label, text in ((self.headline, headline), (self.review, review)):
            label.set_label(text)
            label.set_visible(bool(text))
        self.scan_text.set_label(scan_text)
        self.safe.set_label(safe_label)
        # Without the action service the button could do nothing: it is not shown at all.
        shown = bool(safe_label) and self._can_safe
        self.safe.set_visible(shown)
        self.safe_caption.set_visible(shown)

    def set_busy(self, *, busy: bool) -> None:
        """No second plan while one runs; without the service the button stays off."""
        self._busy = busy
        self.safe.set_sensitive(self._can_safe and not busy)
        self.free_selected.set_sensitive(self._ticked > 0 and not busy)

    def show_selection(self, *, selecting: bool, count: int, total_bytes: int) -> None:
        """The "Libera i selezionati (N, X)" button: shown while selecting, off with none ticked."""
        self._ticked = count
        self.free_selected.set_visible(selecting)
        self.free_selected.set_label(selected_label(count=count, total_bytes=total_bytes))
        self.free_selected.set_sensitive(count > 0 and not self._busy)

    def set_scanning(self, *, scanning: bool) -> None:
        """Spinner on and rescan off while a scan runs."""
        self.spinner.set_visible(scanning)
        self.spinner.set_spinning(scanning)
        self.scan.set_sensitive(not scanning)
