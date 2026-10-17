"""The preferences dialog (RF-50): edits are validated and saved by `AppService.update_config`."""

import logging
from pathlib import Path
from typing import Any

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk

from wimm.config import config_to_raw
from wimm.model.errors import WimmError
from wimm.paths import UserPaths
from wimm.ui.dialogs.preferences_ignored import IgnoredGroups, can_unignore
from wimm.ui.dialogs.preferences_model import GROUPS, collect_changes
from wimm.ui.dialogs.preferences_rows import ERROR_CLASS, Field, build_field

LOGGER = logging.getLogger(__name__)
TITLE = "Preferenze"
APPLY_LABEL = "Applica"
SAVED_TEXT = "Preferenze applicate."
NO_CHANGES_TEXT = "Nessuna modifica."
INVALID_TEXT = "Alcuni valori non sono validi: restano quelli in uso."
SAVE_FAILED_TEXT = "Impossibile salvare le preferenze: {reason}. Riprova."
STATUS_SPACING = 12


class PreferencesDialog(Adw.PreferencesDialog):
    """Fields grouped as in the spec, applied together with the "Applica" button.

    Applying together (not on every change) matters because the pressure thresholds
    depend on each other: moving the warning below the critical one would be rejected
    midway through an edit that is valid as a whole.
    """

    def __init__(self, *, source: Any, paths: UserPaths, home: Path) -> None:
        super().__init__(title=TITLE, search_enabled=False)
        self._source, self._paths, self._home = source, paths, home
        self._config = source.config()
        self.fields: dict[str, Field] = {}
        self._status = Gtk.Label(xalign=0, wrap=True, visible=False)
        page = Adw.PreferencesPage()
        for group in GROUPS:
            page.add(self._build_group(group=group))
        if can_unignore(source=source):
            page.add(IgnoredGroups(source=source).group)
        page.add(self._build_apply_group())
        self.add(page)
        self._load_all()

    @property
    def status_text(self) -> str:
        """The message under the fields: saved, invalid values or a save failure."""
        return self._status.get_label()

    def _build_group(self, *, group: Any) -> Adw.PreferencesGroup:
        widget = Adw.PreferencesGroup(title=group.title, description=group.description)
        for key in group.keys:
            self.fields[key] = build_field(key=key)
            widget.add(self.fields[key].row)
        return widget

    def _build_apply_group(self) -> Adw.PreferencesGroup:
        button = Gtk.Button(label=APPLY_LABEL, halign=Gtk.Align.END)
        button.add_css_class("suggested-action")
        button.connect("clicked", lambda *_a: self.apply())
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=STATUS_SPACING)
        box.append(self._status)
        box.append(button)
        group = Adw.PreferencesGroup()
        group.add(box)
        return group

    def _load_all(self) -> None:
        raw = config_to_raw(config=self._config)
        for key, item in self.fields.items():
            item.load(raw[key])

    def _say(self, *, text: str, is_error: bool) -> None:
        self._status.set_label(text)
        self._status.set_visible(True)
        if is_error:
            self._status.add_css_class(ERROR_CLASS)
        else:
            self._status.remove_css_class(ERROR_CLASS)

    def _save_failed(self, *, reason: str) -> None:
        LOGGER.error("Cannot save the preferences: %s", reason)
        self._say(text=SAVE_FAILED_TEXT.format(reason=reason), is_error=True)

    def apply(self) -> None:
        """Send the changed fields; invalid ones show their error and keep the value in use."""
        for item in self.fields.values():
            item.clear_error()
        shown = {key: item.read() for key, item in self.fields.items()}
        changes = collect_changes(current=config_to_raw(config=self._config), shown=shown)
        if not changes:
            self._say(text=NO_CHANGES_TEXT, is_error=False)
            return
        try:
            result = self._source.update_config(changes=changes, paths=self._paths, home=self._home)
        except OSError as error:
            self._save_failed(reason=str(error.strerror or error))
            return
        except WimmError as error:
            self._save_failed(reason=error.user_message)
            return
        self._config = result.config
        self._load_all()
        for key, message in result.field_errors.items():
            if key in self.fields:
                self.fields[key].show_error(message=message)
        failed = bool(result.field_errors)
        self._say(text=INVALID_TEXT if failed else SAVED_TEXT, is_error=failed)
