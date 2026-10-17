from collections.abc import Callable
from dataclasses import dataclass

from gi.repository import Adw, Gio, GLib, Gtk

from . import ACTIONS_UNAVAILABLE_TOOLTIP

SNOOZE_BUTTON_NAME = "snooze-group"
IGNORE_BUTTON_NAME = "ignore-group"
SNOOZE_GROUP = "notify"
SNOOZE_ACTION = "snooze"
SECONDS_PER_DAY = 86400
SNOOZE_CHOICES = (("1 h", 3600), ("24 h", SECONDS_PER_DAY), ("7 giorni", 7 * SECONDS_PER_DAY))
CONTROLS_TITLE = "Notifiche di questo gruppo"
SNOOZE_LABEL = "Silenzia"
IGNORE_LABEL = "Ignora"
UNIGNORE_LABEL = "Non ignorare più"
SUFFIX_SPACING = 8


@dataclass(frozen=True, slots=True)
class GroupControlHandlers:
    """What the Silenzia and Ignora controls call; the real service provides both."""

    on_snooze: Callable[[str, float], None]
    on_ignore: Callable[[str, bool], None]


def _snooze_menu() -> Gio.Menu:
    menu = Gio.Menu()
    for label, seconds in SNOOZE_CHOICES:
        item = Gio.MenuItem.new(label, None)
        item.set_action_and_target_value(
            f"{SNOOZE_GROUP}.{SNOOZE_ACTION}", GLib.Variant.new_uint32(seconds)
        )
        menu.append_item(item)
    return menu


class GroupControls(Adw.ActionRow):
    """Silenzia (1 h, 24 h, 7 giorni) and Ignora of one group, in its expanded row."""

    def __init__(
        self, *, group_id: str, ignored: bool, handlers: GroupControlHandlers | None
    ) -> None:
        super().__init__(title=CONTROLS_TITLE, use_markup=False)
        self._group_id, self._handlers = group_id, handlers
        self._ignored = ignored
        self._snooze = Gtk.MenuButton(
            label=SNOOZE_LABEL, menu_model=_snooze_menu(), valign=Gtk.Align.CENTER
        )
        self._snooze.set_name(SNOOZE_BUTTON_NAME)
        self._ignore = Gtk.Button(valign=Gtk.Align.CENTER)
        self._ignore.set_name(IGNORE_BUTTON_NAME)
        actions = Gio.SimpleActionGroup()
        action = Gio.SimpleAction.new(SNOOZE_ACTION, GLib.VariantType.new("u"))
        action.connect("activate", self._on_snooze)
        actions.add_action(action)
        self.insert_action_group(SNOOZE_GROUP, actions)
        self._ignore.connect("clicked", self._on_ignore)
        box = Gtk.Box(spacing=SUFFIX_SPACING, valign=Gtk.Align.CENTER)
        box.append(self._snooze)
        box.append(self._ignore)
        self.add_suffix(box)
        self.update(ignored=ignored)
        if handlers is None:
            for control in (self._snooze, self._ignore):
                control.set_sensitive(False)
                control.set_tooltip_text(ACTIONS_UNAVAILABLE_TOOLTIP)

    def update(self, *, ignored: bool) -> None:
        """Show "Ignora" or "Non ignorare più" according to the snapshot."""
        self._ignored = ignored
        self._ignore.set_label(UNIGNORE_LABEL if ignored else IGNORE_LABEL)

    def _on_snooze(self, _action: Gio.SimpleAction, parameter: GLib.Variant) -> None:
        if self._handlers is not None:
            self._handlers.on_snooze(self._group_id, float(parameter.get_uint32()))

    def _on_ignore(self, *_args: object) -> None:
        if self._handlers is not None:
            self._handlers.on_ignore(self._group_id, not self._ignored)
