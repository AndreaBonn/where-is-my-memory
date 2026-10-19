"""F12: GTK in the tests opens the private display, never the user's desktop."""

import os

import pytest
from gi.repository import Gdk

from tests.private_session import OUTER_KEY, SESSION_KEY, PrivateSession

pytestmark = pytest.mark.ui


def test_gtk_opens_the_private_display(pytestconfig: pytest.Config, display: None) -> None:
    session: PrivateSession = pytestconfig.stash[SESSION_KEY]

    default = Gdk.Display.get_default()

    assert default is not None
    assert default.get_name() == session.display
    assert session.display != pytestconfig.stash[OUTER_KEY].get("DISPLAY")
    assert "WAYLAND_DISPLAY" not in os.environ
