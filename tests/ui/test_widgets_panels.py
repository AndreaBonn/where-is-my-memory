import re

import pytest
from gi.repository import GLib, Gtk

from tests.ui.conftest import descendants, main_context_iterate, wait_until
from wimm.model.enums import Risk
from wimm.model.snapshot import Snapshot
from wimm.ui.viewmodel import build_summary
from wimm.ui.views import (
    BarSegment,
    EmptyKind,
    EmptyStateView,
    RowFilters,
)
from wimm.ui.widgets import _STYLE
from wimm.ui.widgets.filter_bar import FilterBar
from wimm.ui.widgets.memory_bar import MemoryBar, segment_classes
from wimm.ui.widgets.risk_badge import make_risk_badge, update_risk_badge
from wimm.ui.widgets.state_views import EmptyView, ErrorView, LoadingView, failure_cause
from wimm.ui.widgets.summary import SummaryPanel

pytestmark = pytest.mark.ui
SEARCH_SETTLE_US = 400_000


def labels_under(widget: Gtk.Widget) -> list[Gtk.Label]:
    return [w for w in descendants(widget) if isinstance(w, Gtk.Label)]


def test_risk_badge_shows_text_and_style_class_and_updates(display: None) -> None:
    badge = make_risk_badge(text="Sicuro", style="success")
    assert badge.get_label() == "Sicuro"
    assert badge.has_css_class("success")

    update_risk_badge(badge=badge, text="Pericolo", style="error")

    assert badge.get_label() == "Pericolo"
    assert badge.has_css_class("error")
    assert not badge.has_css_class("success")


def test_long_risk_badge_wraps_instead_of_widening_the_row(display: None) -> None:
    badge = make_risk_badge(text="Attenzione: leggi prima cosa si perde", style="warning")

    assert badge.get_wrap()
    assert 0 < badge.get_max_width_chars() < len(badge.get_label())


def test_segment_classes_keep_remainders_apart_from_the_palette() -> None:
    def seg(key: str) -> BarSegment:
        return BarSegment(key, key, 1, "1 B", 1, 0.1, key)

    classes = segment_classes(segments=tuple(seg(k) for k in ("A", "kernel_cache", "B", "free")))

    assert classes == ["wimm-seg-0", "wimm-seg-cache", "wimm-seg-1", "wimm-seg-free"]


def test_memory_bar_has_one_block_and_one_visible_legend_line_per_segment(
    display: None, snapshot: Snapshot
) -> None:
    view = build_summary(snapshot=snapshot)
    bar = MemoryBar()

    bar.update(segments=view.segments)

    legend_texts = {label.get_label() for label in labels_under(bar)}
    assert legend_texts == {segment.legend for segment in view.segments}
    assert len(view.segments) >= 2
    blocks = [w for w in descendants(bar) if w.has_css_class("wimm-bar-segment")]
    assert len(blocks) == len(view.segments)


def test_summary_panel_shows_totals_and_a_disabled_stop_all_button(
    display: None, snapshot: Snapshot
) -> None:
    panel = SummaryPanel()

    panel.update(view=build_summary(snapshot=snapshot))

    texts = " | ".join(label.get_label() for label in labels_under(panel))
    assert "Liberabile ora:" in texts
    assert "33 GB usati su 42 GB" in texts
    assert "28 GB liberi su 376 GB" in texts
    assert "Memoria (RAM)" in texts
    assert "memoria quasi piena" not in texts  # the fixture's disk drives the pressure
    (button,) = [w for w in descendants(panel) if w.get_name() == "stop-all-idle"]
    assert isinstance(button, Gtk.Button)
    assert not button.get_sensitive()
    assert button.get_tooltip_text() == "Disponibile con le azioni (fase 3)"


def test_summary_panel_opens_with_a_status_sentence_in_the_pressure_style(
    display: None, snapshot: Snapshot
) -> None:
    panel = SummaryPanel()
    view = build_summary(snapshot=snapshot)

    panel.update(view=view)

    texts = [label.get_label() for label in labels_under(panel)]
    assert texts[0] == "Il disco si sta riempiendo"
    assert texts[1] == view.status_text
    status = next(w for w in descendants(panel) if w.has_css_class("wimm-status"))
    assert status.has_css_class("warning")
    assert panel.get_first_child() is status


def test_safe_button_says_how_much_it_frees_and_what_it_stops(
    display: None, snapshot: Snapshot
) -> None:
    calls: list[str] = []
    panel = SummaryPanel(on_stop_all=lambda: calls.append("stop"))
    view = build_summary(snapshot=snapshot)

    panel.update(view=view)

    (button,) = [w for w in descendants(panel) if w.get_name() == "stop-all-idle"]
    assert isinstance(button, Gtk.Button)
    assert button.get_label() == "Libera 4,2 GB senza rischi"
    assert button.has_css_class("suggested-action")
    assert button.get_sensitive()
    assert view.safe_text in [label.get_label() for label in labels_under(panel)]
    button.emit("clicked")
    assert calls == ["stop"]


def test_safe_button_is_off_when_nothing_can_be_freed_without_risk(
    display: None, snapshot: Snapshot
) -> None:
    from dataclasses import replace

    panel = SummaryPanel(on_stop_all=lambda: None)
    nothing = replace(snapshot, reclaimable_now=replace(snapshot.reclaimable_now, ram=0))

    panel.update(view=build_summary(snapshot=nothing))

    (button,) = [w for w in descendants(panel) if w.get_name() == "stop-all-idle"]
    assert isinstance(button, Gtk.Button)
    assert button.get_label() == "Niente da liberare senza rischi"
    assert not button.get_sensitive()
    panel.set_busy(busy=False)
    assert not button.get_sensitive()


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
    # The cleared search reports later (debounce): wait for it, then count the notifications.
    deadline = GLib.get_monotonic_time() + SEARCH_SETTLE_US
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


def test_error_view_names_the_monitor_and_the_cause(display: None) -> None:
    view = ErrorView()
    view.show_cause(failures=4)

    assert view.page.get_title() == "Il monitor non risponde"
    assert view.page.get_description() == failure_cause(failures=4)
    assert "4 cicli" in failure_cause(failures=4)
    assert view.restart.get_label() == "Riavvia monitor"
    assert view.restart.get_action_name() == "app.restart-monitor"


ADWAITA_PALETTE_FAMILIES = {
    "blue",
    "green",
    "yellow",
    "orange",
    "red",
    "purple",
    "brown",
    "light",
    "dark",
}


def test_every_bar_segment_class_has_a_colour_and_the_stylesheet_parses(
    display: None, snapshot: Snapshot
) -> None:
    errors: list[str] = []
    provider = Gtk.CssProvider()
    provider.connect("parsing-error", lambda _p, _s, error: errors.append(error.message))
    provider.load_from_string(_STYLE)
    segments = build_summary(snapshot=snapshot).segments

    classes = segment_classes(segments=segments)

    assert errors == []
    assert len(classes) == len(segments) >= 5
    for style in classes:
        assert f".{style} {{ background:" in _STYLE
    # GTK drops a rule that names a colour libadwaita does not define (there is no teal).
    families = set(re.findall(r"@([a-z]+)_[1-5]\b", _STYLE))
    assert families <= ADWAITA_PALETTE_FAMILIES
