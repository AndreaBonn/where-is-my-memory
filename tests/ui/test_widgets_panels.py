import re

import pytest
from gi.repository import Gtk

from tests.ui.conftest import descendants
from wimm.model.snapshot import Snapshot
from wimm.ui.disk_texts import DiskTotals
from wimm.ui.viewmodel import build_summary
from wimm.ui.views import (
    BarSegment,
)
from wimm.ui.widgets import _STYLE
from wimm.ui.widgets.memory_bar import MemoryBar, segment_classes
from wimm.ui.widgets.risk_badge import make_risk_badge, update_risk_badge
from wimm.ui.widgets.summary import SummaryPanel

pytestmark = pytest.mark.ui


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
    # The new kernel voices carry a "?" help whose popover labels sit under the bar too.
    helps = {t for s in view.segments for t in (s.help_question, s.help_answer) if t}
    assert helps
    assert legend_texts - helps - {"?"} == {segment.legend for segment in view.segments}
    assert len(view.segments) >= 2
    blocks = [w for w in descendants(bar) if w.has_css_class("wimm-bar-segment")]
    assert len(blocks) == len(view.segments)


def test_summary_panel_shows_totals_and_a_disabled_stop_all_button(
    display: None, snapshot: Snapshot
) -> None:
    panel = SummaryPanel()

    panel.update(view=build_summary(snapshot=snapshot))

    texts = " | ".join(label.get_label() for label in labels_under(panel))
    assert "Puoi liberare 4,2 GB senza perdere niente" in texts
    # Before the first disk scan the disk is unchecked, never "0 B".
    assert "Il disco non è ancora stato controllato" in texts
    assert "0 B" not in texts
    assert "33 GB usati su 42 GB" in texts
    assert "28 GB liberi su 376 GB" in texts
    assert "Memoria (RAM)" in texts
    assert "memoria quasi piena" not in texts  # the fixture's disk drives the pressure
    (button,) = [w for w in descendants(panel) if w.get_name() == "stop-all-idle"]
    assert isinstance(button, Gtk.Button)
    assert not button.get_sensitive()
    assert button.get_tooltip_text() == "Le azioni non sono attive in questa finestra"


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
    assert button.get_label() == "Libera 4,2 GB di memoria"
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
    # A button that could only say "nothing" is not shown at all.
    assert not _cell_shown(button)
    panel.update(view=build_summary(snapshot=snapshot))
    assert _cell_shown(button)


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


def _help_segment(*, size_text: str) -> BarSegment:
    legend = f"Kernel: {size_text}"
    return BarSegment("kernel_unreclaimable", "Kernel", 1, size_text, 10, 0.1, legend, "Q?", "A.")


def test_memory_bar_keeps_the_help_button_when_only_the_sizes_change(display: None) -> None:
    bar = MemoryBar()
    bar.update(segments=(_help_segment(size_text="1,1 GB"),))
    (button,) = [w for w in descendants(bar) if isinstance(w, Gtk.MenuButton)]

    bar.update(segments=(_help_segment(size_text="1,2 GB"),))

    # A rebuilt legend would destroy the button and close an open help popover every sample.
    assert [w for w in descendants(bar) if isinstance(w, Gtk.MenuButton)] == [button]
    assert "Kernel: 1,2 GB" in {label.get_label() for label in labels_under(bar)}
    assert "Kernel: 1,1 GB" not in {label.get_label() for label in labels_under(bar)}


def _cell_shown(button: Gtk.Widget) -> bool:
    cell = button.get_ancestor(Gtk.FlowBoxChild)
    return cell is not None and cell.get_visible()


def _named(panel: Gtk.Widget, name: str) -> Gtk.Button:
    (button,) = [w for w in descendants(panel) if w.get_name() == name]
    assert isinstance(button, Gtk.Button)
    return button


def test_the_disk_button_frees_the_safe_disk_and_the_rest_points_to_the_disco_page(
    display: None, snapshot: Snapshot
) -> None:
    calls: list[str] = []
    panel = SummaryPanel(
        on_free_disk=lambda: calls.append("disk"), on_show_disk=lambda: calls.append("show")
    )
    totals = DiskTotals(safe=5_000_000_000, review=6_600_000_000)

    panel.update(view=build_summary(snapshot=snapshot, disk_totals=totals))

    disk = _named(panel, "free-disk-safe")
    assert disk.get_label() == "Libera 5,0 GB di disco"
    assert _cell_shown(disk) and disk.get_sensitive()
    texts = [label.get_label() for label in labels_under(panel)]
    assert "Puoi liberare 9,2 GB senza perdere niente" in texts
    assert "Altri 6,6 GB se accetti di riscaricare o ricostruire" in texts
    disk.emit("clicked")
    _named(panel, "show-disk-page").emit("clicked")
    assert calls == ["disk", "show"]
    panel.set_busy(busy=True)
    assert not disk.get_sensitive()


def test_before_the_disk_scan_there_is_no_disk_button_and_no_rebuild_line(
    display: None, snapshot: Snapshot
) -> None:
    panel = SummaryPanel(on_free_disk=lambda: None, on_show_disk=lambda: None)

    panel.update(view=build_summary(snapshot=snapshot))

    assert not _cell_shown(_named(panel, "free-disk-safe"))
    review = _named(panel, "show-disk-page").get_parent()
    assert review is not None and not review.get_visible()
