from gi.repository import Adw, Gtk

from wimm.ui.views import EmptyKind, EmptyStateView

LOADING_TITLE = "Raccolta dati in corso…"
SLOW_LOADING_TEXT = "Ci sta mettendo più del previsto"
ERROR_TITLE = "Non riesco a leggere i dati del computer"
RESTART_LABEL = "Riprova adesso"
RESTART_ACTION = "app.restart-monitor"
SPINNER_SIZE = 32
# Inside the scrolled Panoramica a status page takes only its minimum height otherwise.
EMPTY_MIN_HEIGHT = 280
EMPTY_ICONS = {
    EmptyKind.NOTHING_IDLE: "emblem-ok-symbolic",
    EmptyKind.NO_RESULTS: "system-search-symbolic",
    EmptyKind.ALL_CLEAR: "emblem-ok-symbolic",
}


def failure_cause(*, failures: int) -> str:
    """Describe why the monitor is considered unresponsive."""
    return (
        f"Ho provato {failures} volte di fila senza riuscirci. Di solito basta riprovare; "
        "se non passa, i dettagli sono nel registro dell'applicazione."
    )


# Adw.StatusPage is a final type: these views wrap one in `page` instead of subclassing it.
class LoadingView:
    """Spinner with the loading text; mark_slow adds the 15 s fallback line."""

    def __init__(self) -> None:
        self.page = Adw.StatusPage(title=LOADING_TITLE)
        spinner = Gtk.Spinner(
            spinning=True, width_request=SPINNER_SIZE, height_request=SPINNER_SIZE
        )
        spinner.update_property([Gtk.AccessibleProperty.LABEL], [LOADING_TITLE])
        self.page.set_child(spinner)

    def mark_slow(self) -> None:
        """Show the slow-loading explanation."""
        self.page.set_description(SLOW_LOADING_TEXT)

    def reset(self) -> None:
        """Hide the slow-loading explanation."""
        self.page.set_description("")


class ErrorView:
    """Monitor-not-responding page with the cause and the restart button."""

    def __init__(self) -> None:
        self.page = Adw.StatusPage(title=ERROR_TITLE, icon_name="dialog-warning-symbolic")
        # GTK disables a button whose action is unknown, so no enable logic is needed here.
        self.restart = Gtk.Button(
            label=RESTART_LABEL, action_name=RESTART_ACTION, halign=Gtk.Align.CENTER
        )
        self.restart.add_css_class("pill")
        self.page.set_child(self.restart)

    def show_cause(self, *, failures: int) -> None:
        """Explain the failure."""
        self.page.set_description(failure_cause(failures=failures))


class EmptyView:
    """Empty list message, shown verbatim from the view model (spec 10.3)."""

    def __init__(self) -> None:
        self.page = Adw.StatusPage(height_request=EMPTY_MIN_HEIGHT)

    def show_state(self, *, state: EmptyStateView) -> None:
        """Show the message of an EmptyStateView."""
        self.page.set_icon_name(EMPTY_ICONS[state.kind])
        self.page.set_title(state.message)
        self.page.set_description(state.description)
