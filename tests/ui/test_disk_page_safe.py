from datetime import datetime

import pytest
from gi.repository import Gtk

from tests.core.disk_helpers import report
from tests.ui.conftest import WindowFactory, descendants, main_context_iterate
from tests.ui.fakes import FakeDiskSource
from wimm.core.disk_wire import disk_report_from_json
from wimm.model.disk import DiskReport
from wimm.model.enums import ActionKind
from wimm.model.snapshot import Snapshot
from wimm.ui.pages.disk import DiskPage
from wimm.ui.pages.disk_header import SAFE_BUTTON_NAME

pytestmark = pytest.mark.ui
from tests.ui.disk_page_helpers import SAMPLE, buttons_in, make_page, safe_button, show


@pytest.fixture
def sample() -> DiskReport:
    return disk_report_from_json(text=SAMPLE.read_text(encoding="utf-8"))


def test_safe_button_frees_everything_safe_with_one_click(
    display: None, now: datetime, sample: DiskReport
) -> None:
    calls: list[ActionKind] = []
    page = DiskPage(on_rescan=lambda: None, on_section=calls.append)
    show(page, report_=sample, now=now)

    (button,) = [b for b in buttons_in(page) if (b.get_label() or "").endswith("senza rischi")]
    assert (button.get_label() or "").startswith("Libera ")
    assert button.get_visible()
    button.emit("clicked")

    assert calls == [ActionKind.DISK_FREE_SAFE]


def test_safe_button_is_hidden_with_nothing_safe(display: None, now: datetime) -> None:
    page = DiskPage(on_rescan=lambda: None, on_section=lambda _kind: None)
    show(page, report_=report(), now=now)

    (button,) = [b for b in buttons_in(page) if b.get_name() == SAFE_BUTTON_NAME]
    assert not button.get_visible()


def test_safe_button_is_off_while_an_action_runs(
    display: None, now: datetime, sample: DiskReport
) -> None:
    page = DiskPage(on_rescan=lambda: None, on_section=lambda _kind: None)
    show(page, report_=sample, now=now)
    assert safe_button(page).get_sensitive()

    page.set_busy(busy=True)
    assert not safe_button(page).get_sensitive()

    page.set_busy(busy=False)
    assert safe_button(page).get_sensitive()


def test_safe_button_is_absent_without_actions(
    display: None, now: datetime, sample: DiskReport
) -> None:
    page = make_page()  # a source without the action service
    show(page, report_=sample, now=now)

    assert not safe_button(page).get_visible()


def _overview_texts(window: Gtk.Window) -> list[str]:
    overview = window.overview  # type: ignore[attr-defined]
    return [w.get_label() for w in descendants(overview) if isinstance(w, Gtk.Label)]


def test_the_overview_counts_the_disk_only_once_it_is_checked(
    window_factory: WindowFactory, snapshot: Snapshot, sample: DiskReport
) -> None:
    source = FakeDiskSource(snapshot=snapshot, report=None)
    window = window_factory(source)
    main_context_iterate()
    assert any(
        t.startswith("Il disco non è ancora stato controllato") for t in _overview_texts(window)
    )

    source.publish_report(sample)
    main_context_iterate()

    buttons = {w.get_name(): w for w in descendants(window.overview) if isinstance(w, Gtk.Button)}
    # Same safe amount as the Disco page headline above: 3,2 GB.
    assert buttons["free-disk-safe"].get_label() == "Libera 3,2 GB di disco"
    assert "Altri 1,2 GB se accetti di riscaricare o ricostruire" in _overview_texts(window)
    buttons["show-disk-page"].emit("clicked")
    assert window.view_stack.get_visible_child_name() == "disk"
