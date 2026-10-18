from typing import Any

import pytest

from tests.integration.docker_targets import connect
from wimm.collectors.disk_report import DockerDiskSource
from wimm.collectors.docker_engines import FixedEngines

pytestmark = [pytest.mark.integration, pytest.mark.docker]


@pytest.fixture
def client() -> Any:
    try:
        return connect()
    except RuntimeError as error:
        pytest.skip(str(error))


def test_report_counts_match_image_and_volume_listings(client: Any) -> None:
    # `images.list(all=True)` and `volumes.list()` hit different, read-only endpoints
    # than `/system/df` (same data as `docker image ls -a` and `docker volume ls`).
    result = DockerDiskSource(engines=FixedEngines(client=client)).collect()
    disk = result.data
    assert result.error is None
    assert len(disk.images) + disk.images_truncated == len(client.images.list(all=True))
    volume_names = {volume.name for volume in client.volumes.list()}
    assert len(disk.volumes) + disk.volumes_truncated == len(volume_names)
    assert {volume.name for volume in disk.volumes} <= volume_names
