"""A1: the first window shows four plain points and "Ho capito", then never again."""

from pathlib import Path

import pytest
from gi.repository import Adw, Gtk

from tests.ui.conftest import (
    FakeSource,
    WindowFactory,
    descendants,
    main_context_iterate,
    wait_until,
)
from wimm.first_run import is_first_run
from wimm.model.snapshot import Snapshot

pytestmark = pytest.mark.ui


def test_the_first_window_welcomes_once(
    window_factory: WindowFactory, snapshot: Snapshot, tmp_path: Path
) -> None:
    window = window_factory(FakeSource(snapshot=snapshot))
    window.show_group(group_id=None)
    main_context_iterate()
    dialog = window.get_visible_dialog()
    assert isinstance(dialog, Adw.AlertDialog)
    texts = [w.get_label() for w in descendants(dialog) if isinstance(w, Gtk.Label)]
    assert any("Non chiudo mai niente da solo" in text for text in texts)
    assert dialog.get_response_label("close") == "Ho capito"

    dialog.force_close()
    # "closed" arrives at the end of the close animation, not on the next iteration.
    wait_until(lambda: not is_first_run(state_dir=tmp_path / "state"), description="marker")
    again = window_factory(FakeSource(snapshot=snapshot))
    again.show_group(group_id=None)
    main_context_iterate()
    assert again.get_visible_dialog() is None


def test_showing_the_window_again_does_not_stack_a_second_welcome(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    window = window_factory(FakeSource(snapshot=snapshot))
    window.show_group(group_id=None)
    main_context_iterate()
    first = window.get_visible_dialog()
    assert isinstance(first, Adw.AlertDialog)

    window.show_group(group_id=None)
    main_context_iterate()

    assert window.get_visible_dialog() is first
    first.force_close()
    wait_until(lambda: window.get_visible_dialog() is None, description="welcome closed")
