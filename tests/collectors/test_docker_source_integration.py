import logging
import subprocess
from pathlib import Path

import pytest

from tests.collectors.docker_source_helpers import _docker_memory_rows
from wimm.collectors.docker_source import (
    DockerSource,
)
from wimm.model.enums import MetricsSource
from wimm.model.raw import RawContainer

MEMORY_TOLERANCE = 0.05
# Cache moves during the docker samples are absolute (8 MiB measured), not proportional:
# on a small total the relative tolerance alone is tighter than that noise.
MEMORY_NOISE_FLOOR = 8 * 1024 * 1024


def _running_containers() -> tuple[DockerSource, list[RawContainer]]:
    source = DockerSource()
    result = source.collect()
    if not result.data.status.available:
        pytest.skip(reason=f"Docker inaccessible: {result.error}")
    running = [item for item in result.data.containers if item.state == "running"]
    if not running:
        pytest.skip(reason="No running containers to compare")
    return source, running


@pytest.mark.integration
def test_real_docker_availability(caplog: pytest.LogCaptureFixture) -> None:
    result = DockerSource().collect()
    if result.data.status.available:
        assert result.data.status.error is None
        assert result.error is None
    else:
        assert result.data.containers == ()
        assert result.error and result.error == result.data.status.error
    logging.getLogger(__name__).warning(
        "VERIFY Docker available=%s, error=%s", result.data.status.available, result.error
    )


@pytest.mark.integration
def test_real_running_containers_are_read_from_cgroup_files() -> None:
    # The formula itself is pinned exactly by the fake-cgroup unit test above; a second live
    # read cannot pin it, because a cache-heavy container moves by MiB between two reads.
    # What only the real system can show is that every running container's cgroup resolves.
    _, running = _running_containers()
    assert all(item.metrics_source is MetricsSource.CGROUP for item in running)


@pytest.mark.integration
def test_real_total_container_memory_matches_docker_stats() -> None:
    # DoD 3 compares with docker stats. Per container, page cache moves between the active
    # and inactive lists during the ~2 s docker samples (8 MiB measured on a cache-heavy
    # container), so the comparison is on the total, where those moves are small.
    source, running = _running_containers()
    if not Path("/usr/bin/docker").is_file():
        pytest.skip(reason="Docker CLI is not installed")
    output = subprocess.run(
        args=["/usr/bin/docker", "stats", "--no-stream", "--format", "{{.ID}} {{.MemUsage}}"],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    expected = _docker_memory_rows(output=output.stdout)
    after = {item.id: item for item in source.collect().data.containers}
    ours = docker = 0.0
    for item in running:
        identifier = next((key for key in expected if item.id.startswith(key)), None)
        later = after.get(item.id)
        if identifier is None or later is None:
            continue  # container started or stopped between reads
        ours += (item.memory_bytes + later.memory_bytes) / 2
        docker += expected[identifier]
    assert docker > 0
    assert abs(ours - docker) <= max(MEMORY_TOLERANCE * docker, MEMORY_NOISE_FLOOR)
