"""The footer under every page: copyright sign and the author's name, linked to GitHub."""

import pytest
from gi.repository import Gtk

from tests.ui.conftest import FakeSource, WindowFactory, descendants, present_and_settle
from wimm.model.snapshot import Snapshot
from wimm.ui.widgets import icon_only_label

pytestmark = pytest.mark.ui
GITHUB_URL = "https://github.com/AndreaBonn"


def author_links(widget: Gtk.Widget) -> list[Gtk.LinkButton]:
    return [w for w in descendants(widget) if isinstance(w, Gtk.LinkButton)]


def test_footer_shows_copyright_and_links_the_name_to_github(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    window = window_factory(FakeSource(snapshot=snapshot))

    links = author_links(window)

    assert [link.get_uri() for link in links] == [GITHUB_URL]
    assert links[0].get_label() == "Andrea Bonacci"
    assert icon_only_label(button=links[0]) == "Apri il profilo GitHub di Andrea Bonacci"
    footer = links[0].get_parent()
    assert footer is not None
    texts = [w.get_label() for w in descendants(footer) if isinstance(w, Gtk.Label)]
    assert "©" in texts


@pytest.mark.parametrize("page", ["overview", "disk"])
def test_footer_stays_visible_on_every_page(
    window_factory: WindowFactory, snapshot: Snapshot, page: str
) -> None:
    window = window_factory(FakeSource(snapshot=snapshot))
    present_and_settle(window)

    window.view_stack.set_visible_child_name(page)
    present_and_settle(window)

    (link,) = author_links(window)
    assert link.get_mapped()
