"""F9: a list taller than the dialog says how many entries it holds."""

import pytest

from tests.core.planning_helpers import group, proc, snapshot
from tests.ui.test_confirm_dialog import labels, open_dialog, stop
from wimm.ui.dialogs.text import count_text

pytestmark = pytest.mark.ui
COPIES = 24


def test_a_long_stop_says_how_many_entries_the_list_holds(display: None) -> None:
    # 24 copies of one program: the scroller shows a handful, the total counts them all.
    members = tuple(proc(pid=pid) for pid in range(1, COPIES + 1))
    many = snapshot(group(gid="g", name="gitstatusd", members=members))
    one = snapshot(group(gid="g", name="gitstatusd", members=(proc(pid=1),)))

    dialog, _, _ = open_dialog(snap=many, request=stop("g"), subject="gitstatusd")
    single, _, _ = open_dialog(snap=one, request=stop("g"), subject="gitstatusd")

    assert "24 voci nell'elenco" in labels(dialog)
    assert not any("nell'elenco" in text for text in labels(single))


def test_count_text_is_silent_for_a_single_entry() -> None:
    assert count_text(count=2) == "2 voci nell'elenco"
    assert count_text(count=1) is None
    assert count_text(count=0) is None


@pytest.mark.usefixtures("english")
def test_count_text_in_english() -> None:
    assert count_text(count=24) == "24 items in the list"
