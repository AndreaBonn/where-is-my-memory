import errno
import os
import signal
import subprocess
from contextlib import suppress
from threading import Event
from time import monotonic
from typing import cast

import pytest
from gi.repository import Gio, GLib

APP_STARTUP_TIMEOUT_S = 45
POLL_INTERVAL_S = 0.05
SHUTDOWN_TIMEOUT_S = 5


def wait_for_actions(*, connection: Gio.DBusConnection) -> list[str]:
    deadline = monotonic() + APP_STARTUP_TIMEOUT_S
    last_error = "Application did not export actions"
    while monotonic() < deadline:
        try:
            result = connection.call_sync(
                bus_name="io.github.wimm.Test",
                object_path="/io/github/wimm/Test",
                interface_name="org.gtk.Actions",
                method_name="List",
                parameters=None,
                reply_type=None,
                flags=Gio.DBusCallFlags.NONE,
                timeout_msec=500,
                cancellable=None,
            )
            return cast(list[str], result.unpack()[0])
        except GLib.Error as error:
            last_error = str(error)
            Event().wait(timeout=POLL_INTERVAL_S)
    pytest.fail(last_error)


def stop_application(*, application: subprocess.Popen[bytes]) -> None:
    with suppress(ProcessLookupError):
        os.killpg(application.pid, signal.SIGTERM)
    try:
        application.wait(timeout=SHUTDOWN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        os.killpg(application.pid, signal.SIGKILL)
        application.wait(timeout=SHUTDOWN_TIMEOUT_S)
    with pytest.raises(ProcessLookupError) as excinfo:
        os.killpg(application.pid, 0)
    assert excinfo.value.errno == errno.ESRCH
