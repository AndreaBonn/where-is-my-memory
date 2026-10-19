import json
import os
import stat
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.service.inspector_dbus_helpers import private_bus_address as private_bus_address
from wimm.first_run import mark_welcomed

TIMEOUT_S = 15
PROBE = """
from gi.repository import GLib
from wimm.app import create_application

application = create_application()

def updated(service):
    persisted = service._sampler.environment.persisted_last_active
    print('restored=' + ','.join(sorted(map(str, persisted))), flush=True)
    application.activate_action('quit', None)

application.connect('startup', lambda app: app._service.connect('snapshot-updated', updated))
GLib.timeout_add_seconds(8, lambda: application.activate_action('quit', None))
raise SystemExit(application.run(argv=['wimm', '--background']))
"""


@pytest.mark.integration
@pytest.mark.dbus
def test_existing_state_reaches_the_sampler_and_is_saved_on_exit(
    private_bus_address: str, tmp_path: Path
) -> None:
    state_home = tmp_path / "xdg-state"
    state_dir = state_home / "where-is-my-memory"
    state_dir.mkdir(parents=True)
    mark_welcomed(state_dir=state_dir)  # not the first run, which opens the window (A1)
    seeded = datetime.now(tz=UTC) - timedelta(hours=1)
    entry = {"container": "seeded-container", "at": seeded.isoformat()}
    (state_dir / "state.json").write_text(json.dumps({"version": 1, "last_active": [entry]}))
    result = subprocess.run(
        args=[sys.executable, "-"],
        input=PROBE,
        env={
            **os.environ,
            "XDG_STATE_HOME": str(state_home),
            "DBUS_SESSION_BUS_ADDRESS": private_bus_address,
            "WIMM_APP_ID": "io.github.wimm.StateTest",
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=TIMEOUT_S,
    )
    assert result.returncode == 0, result.stderr
    assert "restored=seeded-container" in result.stdout
    target = state_dir / "state.json"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    saved = json.loads(target.read_text())
    # The real app also records processes it saw active (e.g. the foreground app since
    # T-5.5b), saved as {"process": [...]}: only the container entries are checked here.
    containers = [item["container"] for item in saved["last_active"] if "container" in item]
    assert containers == ["seeded-container"]
