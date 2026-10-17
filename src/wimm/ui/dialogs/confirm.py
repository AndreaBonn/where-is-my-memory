from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from wimm.model.actions import Plan
from wimm.model.enums import Risk
from wimm.ui.dialogs.session import ConfirmSession, StepEntry
from wimm.ui.dialogs.text import (
    CANCEL_LABEL,
    EMPTY_TEXT,
    PHRASE_HINT,
    confirm_label,
    dialog_title,
    entry_title,
    reclaim_text,
)
from wimm.ui.widgets import clear_children, install_style

CONFIRM_RESPONSE = "confirm"
CANCEL_RESPONSE = "cancel"
CONTENT_SPACING = 12
WARNING_SPACING = 6
LIST_MAX_HEIGHT = 260
WARNING_CLASS = "wimm-warning"


def _build_group(*, title: str | None) -> Adw.PreferencesGroup:
    group = Adw.PreferencesGroup()
    if title is not None:
        # The group title is markup and has no switch: escape names such as "R&D <lab>".
        group.set_title(GLib.markup_escape_text(title))
    return group


class ConfirmDialog(Adw.AlertDialog):
    """Confirmation of one plan, at the level its risk asks for (spec 8.3).

    Entries can be removed from a multiple action: the session then asks for a new plan
    and the dialog redraws risk, consequences and total from it.
    """

    def __init__(
        self, *, session: ConfirmSession, on_confirm: Callable[[Plan, str | None], None]
    ) -> None:
        super().__init__()
        install_style()
        self._session = session
        self._confirmed = False
        self._on_confirm = on_confirm
        self._warning = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=WARNING_SPACING)
        self._warning.add_css_class(WARNING_CLASS)
        self._phrase = Adw.EntryRow(use_markup=False)
        self._phrase_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self._phrase_box.add_css_class("boxed-list")
        self._phrase_box.append(self._phrase)
        self._phrase_hint = Gtk.Label(label=PHRASE_HINT, xalign=0, wrap=True)
        self._phrase_hint.add_css_class("dim-label")
        self.set_heading(dialog_title(kind=session.kind, subject=session.subject))
        self.add_response(CANCEL_RESPONSE, CANCEL_LABEL)
        self.add_response(CONFIRM_RESPONSE, confirm_label(kind=session.kind))
        self.set_close_response(CANCEL_RESPONSE)
        self.set_default_response(CANCEL_RESPONSE)
        self.set_extra_child(self._build_content())
        self._phrase.connect("changed", lambda *_args: self._update_confirm())
        self.connect("response", self._on_response)
        self.refresh()

    def _build_content(self) -> Gtk.Box:
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=CONTENT_SPACING)
        scroller = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            propagate_natural_height=True,
            max_content_height=LIST_MAX_HEIGHT,
        )
        scroller.set_child(self._build_targets())
        for child in (scroller, self._warning, self._phrase_hint, self._phrase_box):
            content.append(child)
        return content

    def _build_targets(self) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=CONTENT_SPACING)
        groups: dict[str | None, Adw.PreferencesGroup] = {}
        for entry in self._session.entries:
            key = entry.group if self._session.multiple else None
            if key not in groups:
                groups[key] = _build_group(title=key)
                box.append(groups[key])
            groups[key].add(self._build_row(entry=entry))
        return box

    def _build_row(self, *, entry: StepEntry) -> Adw.PreferencesRow:
        if not self._session.multiple or entry.step_id is None:
            return Adw.ActionRow(title=entry.label, use_markup=False)
        row = Adw.SwitchRow(title=entry.label, use_markup=False, active=True)
        row.connect("notify::active", self._on_toggled, entry.step_id)
        return row

    def _on_toggled(self, row: Adw.SwitchRow, _pspec: object, step_id: str) -> None:
        if row.get_active() == self._session.is_included(step_id=step_id):
            return
        self._session.set_included(step_id=step_id, included=row.get_active())
        self.refresh()

    def refresh(self) -> None:
        """Redraw everything that depends on the current plan."""
        plan = self._session.plan
        self.set_body(self._body_text(plan=plan))
        if plan is not None:
            safe = plan.risk is Risk.SAFE
            self.set_response_appearance(
                CONFIRM_RESPONSE,
                Adw.ResponseAppearance.SUGGESTED if safe else Adw.ResponseAppearance.DESTRUCTIVE,
            )
            self._phrase.set_title(entry_title(phrase=plan.confirm_phrase or ""))
        self._show_consequences(plan=plan)
        typed = plan is not None and plan.confirm_phrase is not None
        self._phrase_box.set_visible(typed)
        self._phrase_hint.set_visible(typed)
        self._update_confirm()

    def _body_text(self, *, plan: Plan | None) -> str:
        if plan is None:
            return self._session.notice or EMPTY_TEXT
        return reclaim_text(
            ram=plan.estimated_reclaim_ram,
            disk=plan.estimated_reclaim_disk,
            total=self._session.multiple,
        )

    def _show_consequences(self, *, plan: Plan | None) -> None:
        clear_children(container=self._warning)
        lines = () if plan is None or plan.risk is Risk.SAFE else plan.consequences
        for line in lines:
            self._warning.append(Gtk.Label(label=line, xalign=0, wrap=True))
        self._warning.set_visible(bool(lines))

    def _can_confirm(self) -> bool:
        plan = self._session.plan
        if plan is None or self._confirmed:
            return False
        return plan.confirm_phrase is None or self._phrase.get_text() == plan.confirm_phrase

    def _update_confirm(self) -> None:
        self.set_response_enabled(CONFIRM_RESPONSE, self._can_confirm())

    def _on_response(self, _dialog: Adw.AlertDialog, response: str) -> None:
        plan = self._session.plan
        if response != CONFIRM_RESPONSE or plan is None or not self._can_confirm():
            return
        # One plan, one execution: a second response would only meet PlanNotFound.
        self._confirmed = True
        self.set_response_enabled(CONFIRM_RESPONSE, False)
        typed = self._phrase.get_text() if plan.confirm_phrase is not None else None
        self._on_confirm(plan, typed)
