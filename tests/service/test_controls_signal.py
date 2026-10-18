import os
import signal

import pytest

from tests.integration.live_targets import python_child, spawned
from wimm.service.controls import PsutilProcessControl
from wimm.service.errors import ControlFailed

SLEEPER = "import time; time.sleep(30)"
EXIT_WAIT_S = 10


def test_send_signal_to_a_pid_never_inspected_raises_and_leaves_the_process_alive() -> None:
    with spawned(args=python_child(script=SLEEPER)) as child:
        control = PsutilProcessControl(owner_uid=os.getuid())

        with pytest.raises(ControlFailed, match="not inspected"):
            control.send_signal(pid=child.pid, sig=signal.SIGTERM)

        assert child.poll() is None


def test_send_signal_to_an_inspected_process_delivers_it() -> None:
    with spawned(args=python_child(script=SLEEPER)) as child:
        control = PsutilProcessControl(owner_uid=os.getuid())
        assert control.inspect(pid=child.pid) is not None

        control.send_signal(pid=child.pid, sig=signal.SIGTERM)

        assert child.wait(timeout=EXIT_WAIT_S) == -signal.SIGTERM
