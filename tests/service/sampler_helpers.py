from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from tests.core.helpers import USER_PATH, meminfo, process
from wimm.collectors import CollectorResult
from wimm.collectors.docker_source import DockerSample
from wimm.config import Config
from wimm.model.memory import DiskUsage
from wimm.model.snapshot import DockerStatus
from wimm.paths import UserPaths
from wimm.service.sampler import Collectors, Sampler, SamplerEnvironment

NOW = datetime(2026, 10, 16, tzinfo=UTC)
DISK = DiskUsage(mount="/", total=1000, used=600, free=400)


def make_sampler(tmp_path: Path) -> Sampler:
    collectors = Collectors(
        processes=lambda: CollectorResult(data=()),
        sockets=lambda: CollectorResult(data=()),
        docker=lambda: CollectorResult(
            data=DockerSample(status=DockerStatus(available=True, error=None), containers=())
        ),
        meminfo=lambda: CollectorResult(data=meminfo()),
        disks=lambda: CollectorResult(data=(DISK,)),
        desktop=lambda: CollectorResult(data={}),
    )
    environment = SamplerEnvironment(
        paths=UserPaths(config_dir=tmp_path, state_dir=tmp_path, cache_dir=tmp_path),
        own_pid=999,
        uid=1000,
        home=tmp_path,
    )
    return Sampler(
        collectors=collectors, environment=environment, config=Config(), clock=lambda: NOW
    )


PODMAN_ID = "c0ffee00" * 8
PROCESS_PSS = 500_000_000
PODMAN_SCOPE = USER_PATH + f"user.slice/libpod-{PODMAN_ID}.scope"


def _protected_memory(*, tmp_path: Path, engine_answers: bool) -> int:
    """Memory the snapshot lists as protected, with a Podman container's process running."""
    from tests.core.assemble_helpers import container

    sampler = make_sampler(tmp_path=tmp_path)
    proc = process(
        pid=20, name="app", cmdline=("app",), create_time=1, cgroup=PODMAN_SCOPE, pss=PROCESS_PSS
    )
    listed = replace(container("db"), id=PODMAN_ID)
    result = CollectorResult(
        data=DockerSample(status=DockerStatus(available=True, error=None), containers=(listed,))
    )
    failed = CollectorResult(
        data=DockerSample(status=DockerStatus(available=False, error="down"), containers=()),
        error="down",
    )
    sampler.collectors = replace(
        sampler.collectors,
        processes=lambda: CollectorResult(data=(proc,)),
        docker=lambda: result if engine_answers else failed,
    )
    return sum(item.memory for item in sampler.run_cycle().protected_summary)
