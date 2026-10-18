"""Docker part of the disk report (SPECIFICHE 7.6): one read-only `GET /system/df`."""

import logging
from collections.abc import Mapping
from typing import Any, Protocol

from docker.errors import DockerException

from wimm.core.disk_rules import parse_docker_df, unavailable_docker
from wimm.core.docker_notices import notices_text
from wimm.i18n import N_, _
from wimm.model.disk import DockerDisk

from . import CollectorResult
from .docker_engines import EngineProvider, local_pool

LOGGER = logging.getLogger(__name__)
# `/system/df` walks every image layer and volume, so it is far slower than the 5 s
# used for container listing. 120 s covers hosts with thousands of images; past it the
# report shows Docker as unavailable instead of blocking.
DF_TIMEOUT_S = 120
NO_ENGINE = "no container engine is reachable"
UNEXPECTED_FORMAT = N_("Docker ha risposto in un formato inatteso")
# What a structurally wrong `df` answer raises while it is classified (missing key, list
# where an object is expected, wrong scalar type).
MALFORMED_ANSWER = (KeyError, TypeError, AttributeError, ValueError)


class MalformedDfError(Exception):
    """The engine answered `/system/df` with a shape `parse_docker_df` cannot read."""


class DockerApi(Protocol):
    def df(self) -> Mapping[str, Any]: ...


class DockerClient(Protocol):
    @property
    def api(self) -> DockerApi: ...


class DockerDiskSource:
    """Reads the primary engine (the first resolved), the one the disk actions also use."""

    def __init__(self, engines: EngineProvider | None = None) -> None:
        self._engines = engines

    def collect(self) -> CollectorResult[DockerDisk]:
        """Read `docker system df` without modifying anything.

        Returns
        -------
        CollectorResult[DockerDisk]
            The classified usage; when no engine answers, the call is refused, times out
            or answers something unexpected, an unavailable `DockerDisk` and the reason.
        """
        engine = None
        try:
            if self._engines is None:
                self._engines = local_pool(timeout=DF_TIMEOUT_S)
            view = self._engines.refresh()
            if not view.engines:
                raise DockerException(notices_text(notices=view.notices) or NO_ENGINE)
            engine = view.engines[0]
            client: DockerClient = engine.client
            return CollectorResult(data=_classify(answer=client.api.df()))
        except Exception as error:
            if engine is not None and self._engines is not None:
                self._engines.discard(engine=engine)
            if isinstance(error, MalformedDfError):
                reason = _(UNEXPECTED_FORMAT)
                LOGGER.warning("Docker df answer is malformed: %r", error.__cause__, exc_info=error)
            else:
                reason = str(error) or type(error).__name__
                LOGGER.warning("Docker disk usage unavailable: %s", reason)
            return CollectorResult(data=unavailable_docker(error=reason), error=reason)


def _classify(*, answer: Mapping[str, Any]) -> DockerDisk:
    try:
        return parse_docker_df(df=answer)
    except MALFORMED_ANSWER as error:
        raise MalformedDfError from error
