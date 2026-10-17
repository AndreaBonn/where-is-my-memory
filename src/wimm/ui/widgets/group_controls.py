from collections.abc import Callable
from dataclasses import dataclass

from gi.repository import Adw, Gtk

from . import ACTIONS_UNAVAILABLE_TOOLTIP

SNOOZE_BUTTON_PREFIX = "snooze-group-"
IGNORE_BUTTON_NAME = "ignore-group"
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400
SNOOZE_CHOICES = (
    ("1 ora", SECONDS_PER_HOUR),
    ("1 giorno", SECONDS_PER_DAY),
    ("7 giorni", 7 * SECONDS_PER_DAY),
)
CONTROLS_TITLE = "Non avvisarmi per questo"
CONTROLS_SUBTITLE = "Resta in lista, smetti solo di ricevere avvisi"
IGNORED_SUBTITLE = "Non ricevi avvisi per questo programma"
IGNORE_LABEL = "Mai più"
UNIGNORE_LABEL = "Riattiva gli avvisi"
SUFFIX_SPACING = 6
CONTENT_MARGIN = 12


@dataclass(frozen=True, slots=True)
class GroupControlHandlers:
    """What the snooze and ignore controls call; the real service provides both."""

    on_snooze: Callable[[str, float], None]
    on_ignore: Callable[[str, bool], None]


class GroupControls(Adw.PreferencesRow):
    """P12: "Non avvisarmi per" 1 ora, 1 giorno, 7 giorni or "Mai più", in the expanded row."""

    def __init__(
        self, *, group_id: str, ignored: bool, handlers: GroupControlHandlers | None
    ) -> None:
        super().__init__(title=CONTROLS_TITLE, use_markup=False, activatable=False)
        self._group_id, self._handlers = group_id, handlers
        self._ignored = ignored
        box = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            column_spacing=SUFFIX_SPACING,
            row_spacing=SUFFIX_SPACING,
            homogeneous=False,
        )
        self._snoozes = [self._snooze_button(label=label, seconds=s) for label, s in SNOOZE_CHOICES]
        self._ignore = Gtk.Button(valign=Gtk.Align.CENTER)
        self._ignore.set_name(IGNORE_BUTTON_NAME)
        self._ignore.connect("clicked", self._on_ignore)
        for control in (*self._snoozes, self._ignore):
            box.append(Gtk.FlowBoxChild(child=control, focusable=False))
            if handlers is None:
                control.set_sensitive(False)
                control.set_tooltip_text(ACTIONS_UNAVAILABLE_TOOLTIP)
        self.subtitle = Gtk.Label(xalign=0, wrap=True)
        self.subtitle.add_css_class("dim-label")
        self.subtitle.add_css_class("caption")
        self.set_child(self._content(buttons=box))
        self.update(ignored=ignored)

    def _content(self, *, buttons: Gtk.FlowBox) -> Gtk.Box:
        """Text over a full-width row of buttons: as a row suffix they got one per line."""
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SUFFIX_SPACING)
        for side in ("top", "bottom", "start", "end"):
            getattr(content, f"set_margin_{side}")(CONTENT_MARGIN)
        for child in (Gtk.Label(label=CONTROLS_TITLE, xalign=0, wrap=True), self.subtitle, buttons):
            content.append(child)
        return content

    def _snooze_button(self, *, label: str, seconds: int) -> Gtk.Button:
        button = Gtk.Button(label=label, valign=Gtk.Align.CENTER)
        button.set_name(f"{SNOOZE_BUTTON_PREFIX}{seconds}")
        button.connect("clicked", lambda *_a: self._on_snooze(seconds=seconds))
        return button

    def update(self, *, ignored: bool) -> None:
        """Offer the snooze choices, or only "Riattiva gli avvisi" for an ignored group."""
        self._ignored = ignored
        self._ignore.set_label(UNIGNORE_LABEL if ignored else IGNORE_LABEL)
        self.subtitle.set_label(IGNORED_SUBTITLE if ignored else CONTROLS_SUBTITLE)
        for button in self._snoozes:
            # The flow box child would keep an empty slot if only the button were hidden.
            for widget in (button, button.get_parent()):
                if widget is not None:
                    widget.set_visible(not ignored)

    def _on_snooze(self, *, seconds: int) -> None:
        if self._handlers is not None:
            self._handlers.on_snooze(self._group_id, float(seconds))

    def _on_ignore(self, *_args: object) -> None:
        if self._handlers is not None:
            self._handlers.on_ignore(self._group_id, not self._ignored)
