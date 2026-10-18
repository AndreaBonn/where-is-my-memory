"""Rows of the preferences dialog: one `Field` per configuration key (spec 10.2)."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk

from wimm.i18n import N_, _
from wimm.ui.dialogs.preferences_model import (
    CATEGORIES_KEY,
    LIST_KEYS,
    NUMBER_FIELDS,
    NumberField,
    actionable_categories,
    display_value,
    format_list,
)
from wimm.ui.format import CATEGORY_LABELS

ERROR_CLASS = "error"
ENTRY_WIDTH_CHARS = 30
PAGE_STEP_FACTOR = 10
# R2: titles as sentences, subtitles that say what changes for the user.
TEXTS = {
    "foreground_tracking": (
        N_("Conta come in uso il programma in primo piano"),
        N_("Il programma della finestra che stai usando non viene proposto"),
    ),
    "remote_sessions_actionable": (
        N_("Gestisci anche i programmi lanciati via SSH"),
        N_(
            "Chiudere un programma lanciato via SSH interrompe il lavoro di chi è collegato. "
            "Il server SSH e la shell di accesso restano sempre protetti"
        ),
    ),
    CATEGORIES_KEY: (
        N_("Avvisami per questi tipi di programma"),
        N_("Gli altri non mandano avvisi"),
    ),
    "extra_protected_names": (
        N_("Programmi da non toccare mai"),
        N_("Nomi dei processi separati da virgola, in aggiunta a quelli già protetti"),
    ),
    "devdirs_roots": (
        N_("Cartelle in cui cercare"),
        N_("Percorsi di cartelle, anche fuori dalla tua cartella personale, separati da virgola"),
    ),
}


@dataclass
class Field:
    """A row bound to one configuration key: read what is shown, load a stored value."""

    key: str
    row: Any
    subtitle: str
    read: Callable[[], object]
    load: Callable[[object], None]
    error: str | None = field(default=None, init=False)
    base_subtitle: str = field(default="", init=False)

    def __post_init__(self) -> None:
        self.base_subtitle = self.subtitle

    def set_note(self, *, lines: tuple[str, ...]) -> None:
        """Append plain-text notes (e.g. a missing folder) under the description."""
        self.subtitle = "\n".join((self.base_subtitle, *lines))
        if self.error is None:
            self.row.set_subtitle(self.subtitle)

    def show_error(self, *, message: str) -> None:
        """Mark the row invalid, with the reason as its text (not by colour alone)."""
        self.error = message
        self.row.add_css_class(ERROR_CLASS)
        self.row.set_subtitle(message)
        self.row.set_tooltip_text(message)

    def clear_error(self) -> None:
        """Back to the normal look and description."""
        self.error = None
        self.row.remove_css_class(ERROR_CLASS)
        self.row.set_subtitle(self.subtitle)
        self.row.set_tooltip_text(None)


def _number_field(*, spec: NumberField) -> Field:
    adjustment = Gtk.Adjustment(
        lower=spec.lower,
        upper=spec.upper,
        step_increment=spec.step,
        page_increment=spec.step * PAGE_STEP_FACTOR,
    )
    title, subtitle = _(spec.title), _(spec.subtitle)
    row = Adw.SpinRow(title=title, subtitle=subtitle, adjustment=adjustment, digits=spec.digits)

    def read() -> object:
        row.update()
        return row.get_value()

    return Field(
        key=spec.key,
        row=row,
        subtitle=subtitle,
        read=read,
        load=lambda raw: row.set_value(display_value(field=spec, raw=raw)),
    )


def _switch_field(*, key: str) -> Field:
    title, subtitle = (_(text) for text in TEXTS[key])
    row = Adw.SwitchRow(title=title, subtitle=subtitle)
    return Field(
        key=key,
        row=row,
        subtitle=subtitle,
        read=row.get_active,
        load=lambda raw: row.set_active(bool(raw)),
    )


def _text_field(*, key: str) -> Field:
    title, subtitle = (_(text) for text in TEXTS[key])
    row = Adw.ActionRow(title=title, subtitle=subtitle)
    entry = Gtk.Entry(valign=Gtk.Align.CENTER, width_chars=ENTRY_WIDTH_CHARS)
    entry.update_property([Gtk.AccessibleProperty.LABEL], [title])
    row.add_suffix(entry)
    row.set_activatable_widget(entry)
    return Field(
        key=key,
        row=row,
        subtitle=subtitle,
        read=entry.get_text,
        load=lambda raw: entry.set_text(format_list(items=raw)),
    )


def _categories_field() -> Field:
    title, subtitle = (_(text) for text in TEXTS[CATEGORIES_KEY])
    row = Adw.ExpanderRow(title=title, subtitle=subtitle)
    checks: dict[str, Gtk.CheckButton] = {}
    for category in actionable_categories():
        check = Gtk.CheckButton(name=category.value, valign=Gtk.Align.CENTER)
        sub = Adw.ActionRow(title=_(CATEGORY_LABELS[category]), activatable_widget=check)
        sub.add_prefix(check)
        row.add_row(sub)
        checks[category.value] = check

    def load(raw: object) -> None:
        chosen = set(raw) if isinstance(raw, list) else set()
        for name, check in checks.items():
            check.set_active(name in chosen)

    return Field(
        key=CATEGORIES_KEY,
        row=row,
        subtitle=subtitle,
        read=lambda: frozenset(name for name, check in checks.items() if check.get_active()),
        load=load,
    )


def build_field(*, key: str) -> Field:
    """The row for ``key``, picked by the kind of value it holds."""
    if key in NUMBER_FIELDS:
        return _number_field(spec=NUMBER_FIELDS[key])
    if key == CATEGORIES_KEY:
        return _categories_field()
    if key in LIST_KEYS:
        return _text_field(key=key)
    return _switch_field(key=key)
