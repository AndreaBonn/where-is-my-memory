import os
import subprocess
import sys
from pathlib import Path
from time import monotonic

import pytest

from tests.service.test_inspector_dbus import private_bus_address as private_bus_address
from wimm.first_run import mark_welcomed

STARTUP_TIMEOUT_S = 10
RSS_LIMIT_KIB = 120 * 1024
BACKGROUND_PROBE = """
import os
import subprocess
import sys
from gi.repository import GLib
from wimm.app import create_application

application = create_application()
updates = []
observations = []

def updated(service):
    updates.append(service.snapshot())
    if len(updates) == 1:
        service.request_cycle()
    else:
        assert service is application._service and application._tray is not None
        # No activate() here: activation opens the window and loads GTK by design (6.2).
        observations.append((
            'gi.repository.Gtk' in sys.modules, 'gi.repository.Adw' in sys.modules
        ))
        rss = subprocess.check_output(
            args=['/usr/bin/ps', '-o', 'rss=', '-p', str(os.getpid())], text=True
        ).strip()
        print(f'cycles=2 Gtk=False Adw=False rss_kib={rss}', flush=True)
        application.activate_action('quit', None)

def started(app):
    app._service.connect('snapshot-updated', updated)

application.connect('startup', started)
GLib.timeout_add_seconds(5, lambda: application.activate_action('quit', None))
exit_code = application.run(argv=['wimm', '--background'])
assert len(updates) == 2, f'Expected two snapshots, received {len(updates)}'
assert observations == [(False, False)], f'Unexpected GUI imports: {observations}'
raise SystemExit(exit_code)
"""


@pytest.mark.integration
@pytest.mark.dbus
def test_background_startup_and_two_real_cycles_do_not_load_gtk(private_bus_address: str) -> None:
    # Not the first run: that one opens the window with the welcome (A1).
    mark_welcomed(state_dir=Path(os.environ["XDG_STATE_HOME"]) / "where-is-my-memory")
    started = monotonic()
    result = subprocess.run(
        args=[sys.executable, "-"],
        input=BACKGROUND_PROBE,
        env={
            **os.environ,
            "DBUS_SESSION_BUS_ADDRESS": private_bus_address,
            "WIMM_APP_ID": "io.github.wimm.BackgroundTest",
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=STARTUP_TIMEOUT_S,
    )
    assert result.returncode == 0, result.stderr
    prefix, rss = result.stdout.strip().rsplit(sep="=", maxsplit=1)
    assert prefix == "cycles=2 Gtk=False Adw=False rss_kib"
    assert 0 < int(rss) < RSS_LIMIT_KIB
    assert monotonic() - started < STARTUP_TIMEOUT_S
