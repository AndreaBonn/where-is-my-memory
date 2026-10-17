import os

import pytest

from wimm.collectors.foreground import ForegroundReader, ForegroundStatus

pytestmark = pytest.mark.skipif(
    not os.environ.get("DISPLAY") or os.environ.get("XDG_SESSION_TYPE") != "x11",
    reason="needs a live X11 session",
)


def test_real_x11_read_is_active_or_unavailable_never_raises() -> None:
    state = ForegroundReader.from_environment(enabled=True).read()
    assert state.status in (ForegroundStatus.ACTIVE, ForegroundStatus.UNAVAILABLE)
    assert (state.pid is not None) == (state.status is ForegroundStatus.ACTIVE)
