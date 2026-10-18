from collections.abc import Callable

from gi.repository import Gtk

from wimm.i18n import N_, _
from wimm.ui.views import SummaryView

from . import ACTIONS_UNAVAILABLE_TOOLTIP, SECONDARY_CLASS, clear_children
from .help_button import titled_with_help
from .memory_bar import MemoryBar

MARGIN = 12
SECTION_SPACING = 8
STATUS_COLUMNS = 2
STATUS_COLUMN_SPACING = 12
LINE_SPACING = 2
STATUS_ICON_SIZE = 32
VIDEO_ROW_NAME = "video-memory"
RAM_TITLE = N_("Memoria (RAM)")
DISK_TITLE = N_("Spazio sul disco")
RAM_QUESTION = N_("Cos'è la memoria (RAM)?")
RAM_ANSWER = N_(
    "La memoria (RAM) è lo spazio dove lavorano i programmi aperti. Quando è piena il "
    "computer rallenta. Chiudere un programma la libera subito: i file salvati restano, il "
    "lavoro non salvato in quel programma si perde."
)
DISK_QUESTION = N_("Cos'è lo spazio sul disco?")
DISK_ANSWER = N_(
    "Il disco è dove restano i file anche a computer spento. Quando è quasi pieno non si "
    "riesce più a salvare né ad aggiornare. Dalla scheda Disco puoi liberare spazio: prima di "
    "ogni cancellazione ti diciamo cosa si perde."
)
STATUS_ICONS = {
    "success": "emblem-ok-symbolic",
    "warning": "dialog-warning-symbolic",
    "error": "dialog-error-symbolic",
}


def _section_title(*, text: str) -> Gtk.Label:
    label = Gtk.Label(label=text, xalign=0)
    label.add_css_class("heading")
    return label


def _help_title(*, text: str, question: str, answer: str) -> Gtk.Box:
    return titled_with_help(
        title=_section_title(text=_(text)), question=_(question), answer=_(answer)
    )


def _detail_label() -> Gtk.Label:
    return Gtk.Label(xalign=0, wrap=True, selectable=False)


def _detail_label_with(*, text: str) -> Gtk.Label:
    label = _detail_label()
    label.set_label(text)
    return label


def _headline_label() -> Gtk.Label:
    label = _detail_label()
    label.add_css_class("title-3")
    return label


def _dim_caption() -> Gtk.Label:
    label = _detail_label()
    label.add_css_class("caption")
    label.add_css_class("dim-label")
    label.add_css_class(SECONDARY_CLASS)
    return label


def _build_stop_all(*, on_stop_all: Callable[[], None] | None) -> Gtk.Button:
    button = Gtk.Button()
    button.add_css_class("suggested-action")
    if on_stop_all is None:
        button.set_sensitive(False)
        button.set_tooltip_text(_(ACTIONS_UNAVAILABLE_TOOLTIP))
    else:
        button.connect("clicked", lambda *_args: on_stop_all())
    button.set_name("stop-all-idle")
    return button


class SummaryPanel(Gtk.Box):
    """RAM bar, disk usage, reclaimable totals and the (phase 3) stop-all button."""

    def __init__(self, *, on_stop_all: Callable[[], None] | None = None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=SECTION_SPACING)
        self._ram_text = _headline_label()
        self._ram_details = _dim_caption()
        self._bar = MemoryBar()
        self._note = _dim_caption()
        self._video = self._build_video()
        self._disk_title = _help_title(text=DISK_TITLE, question=DISK_QUESTION, answer=DISK_ANSWER)
        self._disk_text = _headline_label()
        self._disk_bar = Gtk.ProgressBar()
        self._stop_all = _build_stop_all(on_stop_all=on_stop_all)
        self._safe_text = _dim_caption()
        self._can_stop_all = on_stop_all is not None
        self._has_safe = False
        self._busy = False
        for widget in (
            self._build_status(),
            _help_title(text=RAM_TITLE, question=RAM_QUESTION, answer=RAM_ANSWER),
            self._ram_text,
            self._ram_details,
            self._bar,
            self._note,
            self._video,
            self._disk_title,
            self._disk_text,
            self._disk_bar,
            self._build_reclaim_row(),
        ):
            self.append(widget)

    def set_busy(self, *, busy: bool) -> None:
        """Disable "stop all" while an action runs, so a second plan cannot start over it."""
        self._busy = busy
        self._sync_stop_all()

    def _sync_stop_all(self) -> None:
        # Off with nothing safe to free too: a button that can only say "nothing" is noise.
        self._stop_all.set_sensitive(self._can_stop_all and self._has_safe and not self._busy)

    def _build_status(self) -> Gtk.Box:
        """P1: one sentence in the style of the memory pressure, first thing on the page."""
        self._status_icon = Gtk.Image(pixel_size=STATUS_ICON_SIZE, valign=Gtk.Align.CENTER)
        self._status_icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        self._status_title = _section_title(text="")
        self._status_text = _detail_label()
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=LINE_SPACING, hexpand=True)
        texts.append(self._status_title)
        texts.append(self._status_text)
        self._status = Gtk.Box(spacing=STATUS_COLUMN_SPACING)
        self._status.add_css_class("wimm-status")
        self._status.append(self._status_icon)
        self._status.append(texts)
        return self._status

    def _update_status(self, *, view: SummaryView) -> None:
        self._status_title.set_label(view.status_title)
        self._status_text.set_label(view.status_text)
        self._status_icon.set_from_icon_name(STATUS_ICONS[view.status_level])
        for level in STATUS_ICONS:
            self._status.remove_css_class(level)
        self._status.add_css_class(view.status_level)

    def _build_video(self) -> Gtk.Box:
        """Video memory: its own block, apart from the RAM bar and never summed into it."""
        self._video_title = _section_title(text="")
        self._video_lines = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=LINE_SPACING)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=LINE_SPACING, visible=False)
        box.set_name(VIDEO_ROW_NAME)
        box.append(self._video_title)
        box.append(self._video_lines)
        return box

    def _update_video(self, *, view: SummaryView) -> None:
        self._video_title.set_label(view.video_title)
        clear_children(container=self._video_lines)
        for line in view.video_lines:
            self._video_lines.append(_detail_label_with(text=line))
        self._video.set_visible(bool(view.video_lines))

    def _build_reclaim_row(self) -> Gtk.FlowBox:
        self._reclaim = _detail_label()
        self._reclaim.add_css_class("wimm-reclaim")
        row = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            max_children_per_line=STATUS_COLUMNS,
            homogeneous=False,
            column_spacing=STATUS_COLUMN_SPACING,
        )
        action = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=LINE_SPACING)
        action.append(self._stop_all)
        action.append(self._safe_text)
        row.append(self._reclaim)
        row.append(action)
        return row

    def update(self, *, view: SummaryView) -> None:
        """Show a new SummaryView."""
        self._update_status(view=view)
        self._stop_all.set_label(view.safe_label)
        self._safe_text.set_label(view.safe_text)
        self._safe_text.set_visible(bool(view.safe_text))
        self._has_safe = bool(view.safe_text)
        self._sync_stop_all()
        self._ram_text.set_label(view.ram_headline)
        self._ram_details.set_label(view.ram_details)
        self._bar.update(segments=view.segments)
        self._note.set_label(view.kernel_cache_note)
        self._update_video(view=view)
        self._disk_text.set_label(view.disk_headline)
        self._disk_bar.set_fraction(view.disk_fraction)
        self._disk_bar.update_property(
            [Gtk.AccessibleProperty.LABEL],
            [
                _("Uso del disco {mount}: {used} su {total}").format(
                    mount=view.disk_mount, used=view.disk_used, total=view.disk_total
                )
            ],
        )
        self._reclaim.set_label(
            _("Liberabile ora: {ram} di RAM · {disk} di disco").format(
                ram=view.reclaimable_ram, disk=view.reclaimable_disk
            )
        )
