import pytest
from gi.repository import GLib, Gtk

from tests.ui.conftest import descendants, main_context_iterate, wait_until
from wimm.model.enums import Risk
from wimm.ui.views import (
    EmptyKind,
    EmptyStateView,
    RowFilters,
)
from wimm.ui.widgets.filter_bar import FilterBar
from wimm.ui.widgets.state_views import EmptyView, ErrorView, LoadingView, failure_cause

pytestmark = pytest.mark.ui

# Gtk.SearchEntry default search-delay is 150 ms; twice that is how long a duplicate
# notification would need to show up.
SEARCH_DEBOUNCE_X2_US = 300_000


def toggle(bar: FilterBar, prefix: str) -> Gtk.ToggleButton:
    toggles = [w for w in descendants(bar) if isinstance(w, Gtk.ToggleButton)]
    return next(t for t in toggles if (t.get_label() or "").startswith(prefix))


def test_filter_bar_opens_on_what_can_be_freed(display: None) -> None:
    bar = FilterBar(on_changed=lambda _f: None)

    assert bar.filters == RowFilters(only_idle=True)
    assert toggle(bar, "Da liberare").get_active()
    assert not toggle(bar, "Tutto").get_active()


def test_filter_bar_counts_and_more_filters(display: None) -> None:
    seen: list[RowFilters] = []
    bar = FilterBar(on_changed=seen.append)
    bar.set_counts(idle=4, total=6)
    assert (toggle(bar, "Da liberare").get_label(), toggle(bar, "Tutto").get_label()) == (
        "Da liberare (4)",
        "Tutto (6)",
    )

    toggle(bar, "Tutto").set_active(True)
    checks = {c.get_label(): c for c in descendants(bar) if isinstance(c, Gtk.CheckButton)}
    checks["Attenzione"].set_active(True)
    bar.search.set_text("vite")
    wait_until(lambda: bool(seen) and seen[-1].query == "vite", description="debounced query")

    last = seen[-1]
    assert not last.only_idle
    assert last.risks == frozenset({Risk.CAUTION})
    assert last.query == "vite"
    (more,) = [w for w in descendants(bar) if isinstance(w, Gtk.MenuButton)]
    assert more.get_label() == "Altri filtri (1)"


def test_filter_bar_reset_shows_everything_and_notifies_once(display: None) -> None:
    seen: list[RowFilters] = []
    bar = FilterBar(on_changed=seen.append)
    bar.search.set_text("x")
    wait_until(lambda: bool(seen) and seen[-1].query == "x", description="debounced query")
    seen.clear()

    bar.reset()
    # The cleared search reports later (debounce): first wait for the notification itself,
    wait_until(lambda: bool(seen), description="notification after reset")
    # then a real-time window longer than the known debounce, to catch a second one.
    deadline = GLib.get_monotonic_time() + SEARCH_DEBOUNCE_X2_US
    while GLib.get_monotonic_time() < deadline:
        main_context_iterate()

    assert bar.filters == RowFilters()
    assert seen == [RowFilters()]


def test_empty_view_shows_the_view_model_message_verbatim(display: None) -> None:
    view = EmptyView()
    message = "Niente da liberare: il resto è in uso o ancora in osservazione."

    view.show_state(state=EmptyStateView(kind=EmptyKind.NOTHING_IDLE, message=message))

    assert view.page.get_title() == message


def test_empty_view_shows_the_all_clear_description(display: None) -> None:
    view = EmptyView()
    state = EmptyStateView(
        kind=EmptyKind.ALL_CLEAR, message="Tutto in ordine", description="Ti avvisiamo noi."
    )

    view.show_state(state=state)

    assert (view.page.get_title(), view.page.get_description()) == (
        "Tutto in ordine",
        "Ti avvisiamo noi.",
    )
    assert view.page.get_icon_name() == "emblem-ok-symbolic"
    assert view.page.get_size_request()[1] > 0


def test_loading_view_adds_the_slow_text_only_when_marked(display: None) -> None:
    view = LoadingView()
    assert view.page.get_title() == "Raccolta dati in corso…"
    assert not view.page.get_description()

    view.mark_slow()
    assert view.page.get_description() == "Ci sta mettendo più del previsto"

    view.reset()
    assert not view.page.get_description()


def test_error_view_says_in_plain_words_what_failed_and_offers_a_retry(display: None) -> None:
    view = ErrorView()
    view.show_cause(failures=4)

    assert view.page.get_title() == "Non riesco a leggere i dati del computer"
    assert view.page.get_description() == failure_cause(failures=4)
    assert "4 volte di fila" in failure_cause(failures=4)
    assert view.restart.get_label() == "Riprova adesso"
    assert view.restart.get_action_name() == "app.restart-monitor"
