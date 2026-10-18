from collections.abc import Callable

from gi.repository import Gtk

from wimm.i18n import N_, _
from wimm.ui.disk_texts import SAFE_CAPTION
from wimm.ui.views import SummaryView

from . import ACTIONS_UNAVAILABLE_TOOLTIP, SECONDARY_CLASS

SPACING = 6
COLUMNS = 2
COLUMN_SPACING = 12
STOP_ALL_NAME = "stop-all-idle"
FREE_DISK_NAME = "free-disk-safe"
SHOW_DISK_NAME = "show-disk-page"
SHOW_DISK_LABEL = N_("Vedi nella scheda Disco")


def _label(*, css: tuple[str, ...] = ()) -> Gtk.Label:
    label = Gtk.Label(xalign=0, wrap=True)
    for name in css:
        label.add_css_class(name)
    return label


def _caption() -> Gtk.Label:
    return _label(css=("caption", "dim-label", SECONDARY_CLASS))


def _action_button(*, name: str, on_click: Callable[[], None] | None) -> Gtk.Button:
    button = Gtk.Button(halign=Gtk.Align.START)
    button.set_name(name)
    button.add_css_class("suggested-action")
    if on_click is None:
        button.set_sensitive(False)
        button.set_tooltip_text(_(ACTIONS_UNAVAILABLE_TOOLTIP))
    else:
        button.connect("clicked", lambda *_args: on_click())
    return button


class ReclaimPanel(Gtk.Box):
    """The answer first: how much frees without losing anything, and the two ways to do it.

    The memory button stops the idle safe groups, the disk button cleans the safe disk
    rows; a button with nothing to free is not shown. What else frees at a rebuild cost
    is only named here, with a way to the Disco page where each row says what is lost.
    """

    def __init__(
        self,
        *,
        on_stop_all: Callable[[], None] | None = None,
        on_free_disk: Callable[[], None] | None = None,
        on_show_disk: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=SPACING)
        self._headline = _label(css=("title-2",))
        self._details = _label(css=("dim-label",))
        self._stop_all = _action_button(name=STOP_ALL_NAME, on_click=on_stop_all)
        self._free_disk = _action_button(name=FREE_DISK_NAME, on_click=on_free_disk)
        self._ram_caption, self._disk_caption = _caption(), _caption()
        self._disk_caption.set_label(_(SAFE_CAPTION))
        self._review = _label()
        self._show_disk = Gtk.Button(label=_(SHOW_DISK_LABEL), halign=Gtk.Align.START)
        self._show_disk.set_name(SHOW_DISK_NAME)
        self._show_disk.set_visible(on_show_disk is not None)
        if on_show_disk is not None:
            self._show_disk.connect("clicked", lambda *_args: on_show_disk())
        self._acting = {self._stop_all: on_stop_all is not None}
        self._acting[self._free_disk] = on_free_disk is not None
        self._busy = False
        for widget in (self._headline, self._details, self._build_actions(), self._build_review()):
            self.append(widget)

    def _build_actions(self) -> Gtk.FlowBox:
        # A FlowBox puts the two choices side by side and stacks them on a narrow window.
        row = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            max_children_per_line=COLUMNS,
            column_spacing=COLUMN_SPACING,
            homogeneous=False,
        )
        self._choices: dict[Gtk.Button, Gtk.Box] = {}
        for button, caption in (
            (self._stop_all, self._ram_caption),
            (self._free_disk, self._disk_caption),
        ):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACING)
            box.append(button)
            box.append(caption)
            row.append(box)
            self._choices[button] = box
        return row

    def _build_review(self) -> Gtk.Box:
        self._review_row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACING)
        self._review_row.append(self._review)
        self._review_row.append(self._show_disk)
        return self._review_row

    def update(self, *, view: SummaryView) -> None:
        """Show the amounts of a new SummaryView."""
        self._headline.set_label(view.reclaim_headline)
        self._details.set_label(view.reclaim_details)
        self._details.set_visible(bool(view.reclaim_details))
        self._ram_caption.set_label(view.safe_text)
        for button, label in (
            (self._stop_all, view.safe_label),
            (self._free_disk, view.disk_safe_label),
        ):
            button.set_label(label)
            # Hide the FlowBox cell itself: a hidden box would leave an empty cell.
            cell = self._choices[button].get_parent() or self._choices[button]
            cell.set_visible(bool(label))
        self._review.set_label(view.review_text)
        self._review_row.set_visible(bool(view.review_text))
        self._sync()

    def set_busy(self, *, busy: bool) -> None:
        """No second plan while one runs."""
        self._busy = busy
        self._sync()

    def _sync(self) -> None:
        for button, acting in self._acting.items():
            button.set_sensitive(acting and not self._busy)
