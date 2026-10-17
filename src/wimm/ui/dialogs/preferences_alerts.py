"""R3: "Pochi / Normali / Tanti" above the alert settings, with what each choice means."""

from collections.abc import Mapping

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk

from wimm.i18n import N_, _
from wimm.ui.dialogs.preferences_model import NUMBER_FIELDS, raw_value
from wimm.ui.dialogs.preferences_presets import (
    PRESET_KEYS,
    PRESETS,
    Preset,
    matching_preset,
    preset_sentence,
)
from wimm.ui.dialogs.preferences_rows import Field

TITLE = N_("Quanti avvisi vuoi ricevere?")
LINE_SPACING = 8


class PresetPicker:
    """Linked toggles that fill the three alert fields; a hand-made value unselects them."""

    def __init__(self, *, fields: Mapping[str, Field]) -> None:
        self._fields = fields
        self._filling = False
        self.sentence = Gtk.Label(xalign=0, wrap=True)
        self.sentence.add_css_class("dim-label")
        self._toggles: dict[str, Gtk.ToggleButton] = {}
        row = Gtk.Box(halign=Gtk.Align.START)
        row.add_css_class("linked")
        for preset in PRESETS:
            toggle = Gtk.ToggleButton(label=_(preset.name))
            toggle.connect("toggled", self._on_toggled, preset)
            self._toggles[preset.name] = toggle
            row.append(toggle)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=LINE_SPACING)
        box.append(row)
        box.append(self.sentence)
        self.group = Adw.PreferencesGroup(title=_(TITLE))
        self.group.add(box)
        for key in PRESET_KEYS:
            fields[key].row.connect("notify::value", lambda *_a: self.refresh())

    def _shown_values(self) -> dict[str, object]:
        values: dict[str, object] = {}
        for key in PRESET_KEYS:
            shown = self._fields[key].read()
            if isinstance(shown, int | float):
                values[key] = raw_value(field=NUMBER_FIELDS[key], shown=shown)
        return values

    def refresh(self) -> None:
        """Select the preset the fields match, or none, and say what it means."""
        if self._filling:
            return
        preset = matching_preset(values=self._shown_values())
        self._filling = True
        for name, toggle in self._toggles.items():
            toggle.set_active(preset is not None and preset.name == name)
        self._filling = False
        self.sentence.set_label(preset_sentence(preset=preset))

    def _on_toggled(self, toggle: Gtk.ToggleButton, preset: Preset) -> None:
        if self._filling:
            return
        if not toggle.get_active():
            # A toggle is not a radio: clicking the active one again keeps it chosen.
            self.refresh()
            return
        self._filling = True
        try:
            for key, value in preset.values.items():
                self._fields[key].load(value)
        finally:
            self._filling = False
        self.refresh()
