import os

import pytest

from tests.integration.live_targets import spawned
from wimm.collectors import CollectorResult
from wimm.collectors import processes as collector
from wimm.collectors.processes import ProcessReader
from wimm.model.raw import RawProcess
from wimm.service import controls
from wimm.service.controls import PsutilProcessControl

pytestmark = pytest.mark.integration
SLEEPER = ["sleep", "30"]


def without_last_ancestor(
    source: ProcessReader, own_uid: int
) -> CollectorResult[tuple[RawProcess, ...]]:
    """The real collector, minus the most distant process of the chain (it 'vanished')."""
    real = collector.collect_processes(source=source, own_uid=own_uid)
    return CollectorResult(data=real.data[:-1], error=real.error)


def test_process_whose_ancestor_vanished_while_building_the_chain_is_protected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control = PsutilProcessControl(owner_uid=os.getuid())
    with spawned(args=SLEEPER) as child:
        baseline = control.inspect(pid=child.pid)
        if baseline is None or baseline.protected:
            pytest.skip("test child is protected here (no systemd user session cgroup)")
        monkeypatch.setattr(controls, "collect_processes", without_last_ancestor)

        degraded = control.inspect(pid=child.pid)

        assert degraded is not None and degraded.protected
