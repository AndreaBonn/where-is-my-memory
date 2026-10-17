"""The "Lingua" row: two flag toggles that switch the interface at once, never on "Applica"."""

import logging
from collections.abc import Callable

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, GLib, Gtk

from wimm.i18n import ENGLISH, ITALIAN, N_, _, current_language

LOGGER = logging.getLogger(__name__)
TITLE = N_("Lingua")
DESCRIPTION = N_("La lingua di finestra, menu e notifiche. Il cambio vale subito.")
# Each language is named in itself, so a reader who cannot read the other one still finds it.
CHOICES = ((ITALIAN, "🇮🇹", "Italiano"), (ENGLISH, "🇺🇸", "English"))
SET_LANGUAGE_ACTION = "win.set-language"
FLAG_CLASS = "wimm-flag"


def request_language(*, widget: Gtk.Widget, language: str) -> bool:
    """Ask the application to switch; the window that holds ``widget`` is then rebuilt.

    Returns False when no ancestor handles the action, so nothing will switch.
    """
    handled = widget.activate_action(SET_LANGUAGE_ACTION, GLib.Variant("s", language))
    if not handled:
        LOGGER.warning(
            "No %s action above the preferences: language unchanged", SET_LANGUAGE_ACTION
        )
    return bool(handled)


class LanguageGroup:
    """Preferences group with one toggle per language; the active one is pressed."""

    def __init__(self, *, on_choose: Callable[[str], bool]) -> None:
        self._on_choose = on_choose
        self.group = Adw.PreferencesGroup(title=_(TITLE), description=_(DESCRIPTION))
        self.buttons: dict[str, Gtk.ToggleButton] = {}
        box = Gtk.Box(spacing=0, valign=Gtk.Align.CENTER, css_classes=["linked"])
        for language, flag, name in CHOICES:
            box.append(self._button(language=language, flag=flag, name=name))
        # The row names the active language: the group title already says "Lingua".
        active = next(name for language, _flag, name in CHOICES if language == current_language())
        self.row = Adw.ActionRow(title=active)
        self.row.add_suffix(box)
        self.group.add(self.row)

    def _button(self, *, language: str, flag: str, name: str) -> Gtk.ToggleButton:
        button = Gtk.ToggleButton(
            label=flag, tooltip_text=name, active=language == current_language()
        )
        button.add_css_class(FLAG_CLASS)
        button.update_property([Gtk.AccessibleProperty.LABEL], [name])
        if self.buttons:
            button.set_group(next(iter(self.buttons.values())))
        button.connect("toggled", self._toggled, language)
        self.buttons[language] = button
        return button

    def _toggled(self, button: Gtk.ToggleButton, language: str) -> None:
        if not button.get_active() or language == current_language():
            return
        if not self._on_choose(language):
            # Nothing switched: press the active language again instead of lying.
            self.buttons[current_language()].set_active(True)
