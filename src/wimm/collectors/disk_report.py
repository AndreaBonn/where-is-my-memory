"""Docker part of the disk report (SPECIFICHE 7.6): one read-only `GET /system/df`."""

import logging
from collections.abc import Mapping
from typing import Any, Protocol

import docker

from wimm.core.disk_rules import parse_docker_df, unavailable_docker
from wimm.model.disk import DockerDisk

from . import CollectorResult

LOGGER = logging.getLogger(__name__)
# `/system/df` walks every image layer and volume, so it is far slower than the 5 s
# used for container listing. 120 s covers hosts with thousands of images; past it the
# report shows Docker as unavailable instead of blocking.
DF_TIMEOUT_S = 120


class DockerApi(Protocol):
    def df(self) -> Mapping[str, Any]: ...


class DockerClient(Protocol):
    @property
    def api(self) -> DockerApi: ...


class DockerDiskSource:
    def __init__(self, reader: DockerClient | None = None) -> None:
        self._reader = reader

    def collect(self) -> CollectorResult[DockerDisk]:
        """Read `docker system df` without modifying anything.

        Returns
        -------
        CollectorResult[DockerDisk]
            The classified usage; when Docker is unreachable, refuses the call, times out
            or answers something unexpected, an unavailable `DockerDisk` and the reason.
        """
        try:
            if self._reader is None:
                self._reader = docker.from_env(timeout=DF_TIMEOUT_S)
            return CollectorResult(data=parse_docker_df(df=self._reader.api.df()))
        except Exception as error:
            reason = str(error) or type(error).__name__
            LOGGER.warning("Docker disk usage unavailable: %s", reason)
            return CollectorResult(data=unavailable_docker(error=reason), error=reason)
