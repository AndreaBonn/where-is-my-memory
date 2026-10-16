import json
import stat
from pathlib import Path

import pytest
from gi.repository import Gtk

from tests.ui.conftest import (
    FakeSource,
    WindowFactory,
    descendants,
    main_context_iterate,
    wait_until,
)
from wimm.model.snapshot import Snapshot
from wimm.ui.window_state import (
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    MAX_WINDOW_SIZE,
    MIN_HEIGHT,
    MIN_WIDTH,
    STATE_FILE,
    load_window_size,
    save_window_size,
)

pytestmark = pytest.mark.ui


def test_window_size_roundtrips_through_a_private_json_file(tmp_path: Path) -> None:
    path = tmp_path / "state" / STATE_FILE

    save_window_size(path=path, width=1111, height=555)

    assert json.loads(path.read_text()) == {"width": 1111, "height": 555}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert load_window_size(path=path) == (1111, 555)


@pytest.mark.parametrize(
    "content",
    ["not json", "[]", '{"width": "wide", "height": 5}', '{"width": true, "height": 700}', "{}"],
)
def test_unreadable_window_state_falls_back_to_the_default(tmp_path: Path, content: str) -> None:
    path = tmp_path / STATE_FILE
    path.write_text(content)

    assert load_window_size(path=path) == (DEFAULT_WIDTH, DEFAULT_HEIGHT)


def test_missing_window_state_gives_the_default_and_small_sizes_are_raised(tmp_path: Path) -> None:
    path = tmp_path / STATE_FILE
    assert load_window_size(path=path) == (DEFAULT_WIDTH, DEFAULT_HEIGHT)

    path.write_text('{"width": 10, "height": 20}')

    assert load_window_size(path=path) == (MIN_WIDTH, MIN_HEIGHT)


def test_oversized_window_state_is_clamped_with_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / STATE_FILE
    path.write_text('{"width": 3000000000, "height": 99999}')

    size = load_window_size(path=path)

    assert size == (MAX_WINDOW_SIZE, MAX_WINDOW_SIZE)
    assert sum("oversized" in r.getMessage() for r in caplog.records) == 2


def test_in_range_window_state_logs_no_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / STATE_FILE
    path.write_text('{"width": 800, "height": 600}')

    assert load_window_size(path=path) == (800, 600)
    assert not caplog.records


def test_a_huge_saved_size_still_opens_the_window(
    window_factory: WindowFactory, snapshot: Snapshot, tmp_path: Path
) -> None:
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    (state / STATE_FILE).write_text('{"width": 3000000000, "height": 3000000000}')

    window = window_factory(FakeSource(snapshot=snapshot))

    assert window.get_default_size() == (MAX_WINDOW_SIZE, MAX_WINDOW_SIZE)


def test_closing_saves_the_size_and_a_new_window_reads_it(
    window_factory: WindowFactory,
    snapshot: Snapshot,
    tmp_path: Path,
) -> None:
    first = window_factory(FakeSource(snapshot=snapshot))
    first.set_default_size(700, 500)
    first.present()
    wait_until(lambda: first.get_width() > 0, description="first layout")

    first.emit("close-request")

    saved = json.loads((tmp_path / "state" / STATE_FILE).read_text())
    assert (saved["width"], saved["height"]) == (700, 500)
    second = window_factory(FakeSource(snapshot=snapshot))
    assert second.get_default_size() == (700, 500)


def test_narrow_layout_hides_the_secondary_column_and_restores_it(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    window = window_factory(FakeSource(snapshot=snapshot))
    widget = window.overview.group_widgets["g_3f9a1c"]
    reclaim = next(
        w
        for w in descendants(widget)
        if isinstance(w, Gtk.Label) and w.has_css_class("wimm-reclaim")
    )
    assert reclaim.get_visible()

    window.overview.set_narrow(narrow=True)
    assert not reclaim.get_visible()

    window.overview.set_narrow(narrow=False)
    assert reclaim.get_visible()


def test_narrow_window_layout_emits_no_gtk_warnings(
    window_factory: WindowFactory, snapshot: Snapshot, capfd: pytest.CaptureFixture[str]
) -> None:
    window = window_factory(FakeSource(snapshot=snapshot))
    window.set_default_size(MIN_WIDTH, MIN_HEIGHT)
    window.present()
    wait_until(lambda: window.get_width() > 0, description="first layout")
    main_context_iterate()

    assert "minimum" not in capfd.readouterr().err
    assert window.get_size_request() == (MIN_WIDTH, MIN_HEIGHT)


def test_breakpoint_switches_to_one_column_below_600_px(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    window = window_factory(FakeSource(snapshot=snapshot))
    window.set_default_size(MIN_WIDTH, 720)
    window.present()
    widget = window.overview.group_widgets["g_3f9a1c"]
    reclaim = next(
        w
        for w in descendants(widget)
        if isinstance(w, Gtk.Label) and w.has_css_class("wimm-reclaim")
    )

    wait_until(lambda: not reclaim.get_visible(), description="narrow layout")
    assert window.get_width() < 600
