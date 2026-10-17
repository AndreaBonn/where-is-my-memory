from collections.abc import Callable, Sequence

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from wimm.ui.outcome import StepReport
from wimm.ui.widgets import install_style

CLOSE_RESPONSE = "close"
CLOSE_LABEL = "Chiudi"
HEADING = "Esito"
FORCE_LABEL = "Forza chiusura"
CONTENT_SPACING = 12


class OutcomeDialog(Adw.AlertDialog):
    """What happened to each step of an executed action, and how much it freed."""

    def __init__(
        self, *, reports: Sequence[StepReport], on_force: Callable[[StepReport], None]
    ) -> None:
        super().__init__()
        install_style()
        self.set_heading(HEADING)
        self.add_response(CLOSE_RESPONSE, CLOSE_LABEL)
        self.set_close_response(CLOSE_RESPONSE)
        self._freed = Gtk.Label(xalign=0, wrap=True, visible=False)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=CONTENT_SPACING)
        group = Adw.PreferencesGroup()
        for report in reports:
            group.add(self._build_row(report=report, on_force=on_force))
        for child in (group, self._freed):
            content.append(child)
        self.set_extra_child(content)

    def set_freed(self, *, text: str | None) -> None:
        """Show the measured recovery line, or hide it."""
        self._freed.set_label(text or "")
        self._freed.set_visible(text is not None)

    @staticmethod
    def _build_row(*, report: StepReport, on_force: Callable[[StepReport], None]) -> Adw.ActionRow:
        row = Adw.ActionRow(title=report.label, subtitle=report.status_text, use_markup=False)
        if report.can_force:
            button = Gtk.Button(label=FORCE_LABEL, valign=Gtk.Align.CENTER)
            button.add_css_class("destructive-action")
            button.connect("clicked", lambda *_args: on_force(report))
            row.add_suffix(button)
        return row
