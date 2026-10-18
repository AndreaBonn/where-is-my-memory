"""Docker part of the disk report (SPECIFICHE 7.6): read-only `GET /system/df`.

Every image with digests is also inspected (`GET /images/{id}/json`) to learn whether a
registry holds it: under the containerd store a local build carries digests too.
"""

import logging
import time
from collections.abc import Mapping
from typing import Any, Protocol

from docker.errors import DockerException

from wimm.core.disk_rules import parse_docker_df, unavailable_docker
from wimm.core.docker_notices import notices_text
from wimm.core.image_provenance import identity_expected, with_provenance
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
# Total time for the per-image inspections: an engine stalling halfway would otherwise
# cost one DF_TIMEOUT_S per image. Past it the rest count as local builds.
INSPECT_BUDGET_S = 30


class MalformedDfError(Exception):
    """The engine answered `/system/df` with a shape `parse_docker_df` cannot read."""


class DockerApi(Protocol):
    api_version: str

    def df(self) -> Mapping[str, Any]: ...

    def inspect_image(self, image: str) -> Mapping[str, Any]: ...


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
            return CollectorResult(data=_read(client=engine.client))
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


def _read(*, client: DockerClient) -> DockerDisk:
    """`df` classified, then each image's provenance checked against the engine."""
    docker = _classify(answer=client.api.df())
    inspected = _inspect_digested(api=client.api, docker=docker)
    identity = identity_expected(api_version=client.api.api_version)
    return with_provenance(docker=docker, inspected=inspected, identity=identity)


def _classify(*, answer: Mapping[str, Any]) -> DockerDisk:
    try:
        return parse_docker_df(df=answer)
    except MALFORMED_ANSWER as error:
        raise MalformedDfError from error


def _inspect_digested(*, api: DockerApi, docker: DockerDisk) -> dict[str, Mapping[str, Any] | None]:
    """Inspect answers of the images whose digests might mean a registry holds them.

    A failed inspection, or one past `INSPECT_BUDGET_S`, maps to None: the image then counts
    as a local build, so an error can only make a removal look riskier, never safer.
    """
    found: dict[str, Mapping[str, Any] | None] = {}
    deadline = time.monotonic() + INSPECT_BUDGET_S
    for image in docker.images:
        if image.local_build or time.monotonic() > deadline:
            continue
        try:
            found[image.id] = api.inspect_image(image=image.id)
        except Exception:
            # One odd answer must not take the whole Docker report down with it.
            LOGGER.warning("Image %s not inspected, kept as a local build", image.id, exc_info=True)
    return found
