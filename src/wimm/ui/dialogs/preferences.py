"""The preferences dialog (RF-50): edits are validated and saved by `AppService.update_config`."""

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk

from wimm.collectors.foreground import X11_SESSION
from wimm.config import config_to_raw
from wimm.config_messages import root_refusal_message
from wimm.i18n import N_, _
from wimm.model.errors import WimmError
from wimm.paths import UserPaths
from wimm.ui.dialogs.preferences_alerts import PresetPicker
from wimm.ui.dialogs.preferences_focus import focus_at_end
from wimm.ui.dialogs.preferences_ignored import IgnoredGroups, can_unignore
from wimm.ui.dialogs.preferences_language import LanguageGroup, request_language
from wimm.ui.dialogs.preferences_model import (
    ADVANCED_GROUPS,
    ESSENTIAL_GROUPS,
    RootState,
    RootStatus,
    collect_changes,
    root_statuses,
)
from wimm.ui.dialogs.preferences_presets import recommended_values
from wimm.ui.dialogs.preferences_rows import ERROR_CLASS, Field, build_field
from wimm.ui.disk_texts import MISSING_ROOT_TEXT, REFUSED_ROOT_TEXT
from wimm.ui.format import home_relative

LOGGER = logging.getLogger(__name__)
TITLE = N_("Preferenze")
APPLY_LABEL = N_("Applica")
SAVED_TEXT = N_("Preferenze applicate.")
NO_CHANGES_TEXT = N_("Nessuna modifica.")
INVALID_TEXT = N_("Alcuni valori non sono validi: restano quelli in uso.")
SAVE_FAILED_TEXT = N_("Impossibile salvare le preferenze: {reason}. Riprova.")
RESET_LABEL = N_("Ripristina i valori consigliati")
RESET_HINT = N_(
    "Tornano come all'inizio anche i tipi di programma per cui ricevi avvisi; i programmi da "
    "non toccare e le cartelle in cui cercare restano come sono."
)
INVALID_ADVANCED_TEXT = N_(
    "Alcuni valori in Impostazioni avanzate non sono validi: restano quelli in uso."
)
ADVANCED_TITLE = N_("Impostazioni avanzate")
ADVANCED_SUBTITLE = N_("Come si capisce se è in uso, soglie, chiusura e cartelle ({count} voci)")
FOREGROUND_KEY = "foreground_tracking"
ROOTS_KEY = "devdirs_roots"
NO_X11_TEXT = N_("Non disponibile su questo desktop: funziona solo con X11")
STATUS_SPACING = 12


def _root_note(*, status: RootStatus) -> str:
    """The plain-language line under the folders entry for a missing or refused folder."""
    shown = home_relative(path=status.path, home=Path.home())
    if status.state is RootState.MISSING:
        return _(MISSING_ROOT_TEXT).format(path=shown)
    if status.state is RootState.REFUSED and status.reason is not None:
        reason = root_refusal_message(reason=status.reason)
        return _(REFUSED_ROOT_TEXT).format(path=shown, reason=reason)
    return ""


class PreferencesDialog(Adw.PreferencesDialog):
    """Fields grouped as in the spec, applied together with the "Applica" button.

    Applying together (not on every change) matters because the pressure thresholds
    depend on each other: moving the warning below the critical one would be rejected
    midway through an edit that is valid as a whole.
    """

    def __init__(
        self, *, source: Any, paths: UserPaths, home: Path, session_type: str | None = None
    ) -> None:
        super().__init__(title=_(TITLE), search_enabled=False)
        self._source, self._paths, self._home = source, paths, home
        self._config = source.config()
        self.fields: dict[str, Field] = {}
        self._statuses: list[Gtk.Label] = []
        page = Adw.PreferencesPage()
        self.language = LanguageGroup(
            on_choose=lambda language: request_language(widget=self, language=language)
        )
        page.add(self.language.group)
        essentials = [self._build_group(group=group) for group in ESSENTIAL_GROUPS]
        self.advanced = self._build_advanced()
        # Mapped is not on screen: a page still mapped during its pop animation would take the
        # focus and then vanish, so track the navigation state from the page's own signals.
        self._advanced_on_screen = False
        self.advanced.connect("showing", lambda *_a: setattr(self, "_advanced_on_screen", True))
        self.advanced.connect("hiding", lambda *_a: setattr(self, "_advanced_on_screen", False))
        self._presets = PresetPicker(fields=self.fields)
        for group in (self._presets.group, *essentials, self._build_advanced_link()):
            page.add(group)
        if can_unignore(source=source):
            page.add(IgnoredGroups(source=source).group)
        page.add(self._build_apply_group(with_reset=True))
        self.add(page)
        self._limit_foreground(session_type=session_type)
        self._load_all()

    @property
    def preset_text(self) -> str:
        """R3: what the chosen alert level means, or that the values are set by hand."""
        return self._presets.sentence.get_label()

    @property
    def status_text(self) -> str:
        """The message under the fields: saved, invalid values or a save failure."""
        return self._statuses[0].get_label()

    def _build_group(self, *, group: Any) -> Adw.PreferencesGroup:
        widget = Adw.PreferencesGroup(title=_(group.title), description=_(group.description))
        for key in group.keys:
            self.fields[key] = build_field(key=key)
            widget.add(self.fields[key].row)
        return widget

    def _build_advanced(self) -> Adw.NavigationPage:
        """R1: the measuring, threshold, closing and folder settings, one level down."""
        page = Adw.PreferencesPage()
        for group in ADVANCED_GROUPS:
            page.add(self._build_group(group=group))
        page.add(self._build_apply_group(with_reset=False))
        view = Adw.ToolbarView(content=page)
        view.add_top_bar(Adw.HeaderBar())
        return Adw.NavigationPage(title=_(ADVANCED_TITLE), child=view)

    def _build_advanced_link(self) -> Adw.PreferencesGroup:
        count = sum(len(group.keys) for group in ADVANCED_GROUPS)
        self.advanced_row = Adw.ActionRow(
            title=_(ADVANCED_TITLE),
            subtitle=_(ADVANCED_SUBTITLE).format(count=count),
            activatable=True,
        )
        self.advanced_row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        self.advanced_row.connect("activated", lambda *_a: self.push_subpage(self.advanced))
        group = Adw.PreferencesGroup()
        group.add(self.advanced_row)
        return group

    def _build_apply_group(self, *, with_reset: bool) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup()
        status = Gtk.Label(xalign=0, wrap=True, visible=False)
        self._statuses.append(status)
        button = Gtk.Button(label=_(APPLY_LABEL), halign=Gtk.Align.END)
        button.add_css_class("suggested-action")
        button.connect("clicked", lambda *_a: self.apply())
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=STATUS_SPACING)
        box.append(status)
        if with_reset:
            self.reset_button = Gtk.Button(label=_(RESET_LABEL), halign=Gtk.Align.START)
            self.reset_button.connect("clicked", lambda *_a: self.reset())
            hint = Gtk.Label(label=_(RESET_HINT), xalign=0, wrap=True)
            hint.add_css_class("caption")
            hint.add_css_class("dim-label")
            box.append(self.reset_button)
            box.append(hint)
        box.append(button)
        group.add(box)
        return group

    def _limit_foreground(self, *, session_type: str | None) -> None:
        """R5: following the foreground window works only on X11; elsewhere say so."""
        if session_type == X11_SESSION:
            return
        item = self.fields[FOREGROUND_KEY]
        no_x11 = _(NO_X11_TEXT)
        item.subtitle = no_x11
        item.row.set_subtitle(no_x11)
        item.row.set_sensitive(False)

    def _load_all(self) -> None:
        raw = config_to_raw(config=self._config)
        for key, item in self.fields.items():
            item.load(raw[key])
        self._presets.refresh()
        notes = (_root_note(status=status) for status in root_statuses(config=self._config))
        self.fields[ROOTS_KEY].set_note(lines=tuple(note for note in notes if note))

    def show_folders(self) -> None:
        """Open the advanced page with the cursor in the folders entry (the "Scegli" action)."""
        row = self.fields[ROOTS_KEY].row
        entry = row.get_activatable_widget()
        if self._advanced_on_screen:
            focus_at_end(row=row, entry=entry)
            return
        # The entry takes focus only once the page is on screen.
        handler = 0

        def focus_entry(*_args: object) -> None:
            self.advanced.disconnect(handler)
            focus_at_end(row=row, entry=entry)

        handler = self.advanced.connect("shown", focus_entry)
        self.push_subpage(self.advanced)

    def reset(self) -> None:
        """R4: put back the recommended values and apply them at once.

        Names and folders keep the value in use, even an edit not applied yet, and an
        option the session cannot use keeps its value too.
        """
        raw = config_to_raw(config=self._config)
        for key, item in self.fields.items():
            item.load(raw[key])
        for key, value in recommended_values().items():
            if self.fields[key].row.get_sensitive():
                self.fields[key].load(value)
        self.apply()

    def _say(self, *, text: str, is_error: bool) -> None:
        for status in self._statuses:
            status.set_label(text)
            status.set_visible(True)
            if is_error:
                status.add_css_class(ERROR_CLASS)
            else:
                status.remove_css_class(ERROR_CLASS)

    def _save_failed(self, *, reason: str) -> None:
        LOGGER.error("Cannot save the preferences: %s", reason)
        self._say(text=_(SAVE_FAILED_TEXT).format(reason=reason), is_error=True)

    def apply(self) -> None:
        """Send the changed fields; invalid ones show their error and keep the value in use."""
        for item in self.fields.values():
            item.clear_error()
        shown = {key: item.read() for key, item in self.fields.items()}
        changes = collect_changes(current=config_to_raw(config=self._config), shown=shown)
        if not changes:
            self._say(text=_(NO_CHANGES_TEXT), is_error=False)
            return
        try:
            result = self._source.update_config(changes=changes, paths=self._paths, home=self._home)
        except OSError as error:
            self._save_failed(reason=str(error.strerror or error))
            return
        except WimmError as error:
            self._save_failed(reason=_(error.user_message))
            return
        self._config = result.config
        self._load_all()
        for key, message in result.field_errors.items():
            if key in self.fields:
                self.fields[key].show_error(message=message)
        failed = bool(result.field_errors)
        self._say(text=self._result_text(errors=result.field_errors), is_error=failed)

    def _result_text(self, *, errors: Mapping[str, str]) -> str:
        """Saved, or invalid; an error on the advanced page is named from the main one."""
        if not errors:
            return _(SAVED_TEXT)
        hidden = any(
            self.fields[key].row.is_ancestor(self.advanced) for key in errors if key in self.fields
        )
        return _(INVALID_ADVANCED_TEXT) if hidden else _(INVALID_TEXT)
