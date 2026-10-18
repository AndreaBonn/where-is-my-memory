"""The container engines on this machine: one client per safe local endpoint (F9, S8).

Clients are built on the resolved unix sockets, never with ``docker.from_env()``, which
would follow an unvalidated ``DOCKER_HOST`` such as ``tcp://``.
"""

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any, Protocol

import docker

from wimm.core.docker_endpoint import UNIX_PREFIX, DockerEndpoint, EndpointResolution
from wimm.core.docker_notices import EngineNotice, NoticeCode, rejection_notice
from wimm.model.actions import EngineIdentity

from .docker_endpoint_facts import resolve_local_docker_endpoints

LOGGER = logging.getLogger(__name__)
ENGINE_ID_KEY = "ID"
FIXED_ENGINE_PATH = "/var/run/docker.sock"
BACKOFF_INITIAL_S = 60.0
BACKOFF_MAX_S = 600.0
BACKOFF_FACTOR = 2


class Connect(Protocol):
    def __call__(self, *, found: DockerEndpoint) -> Any: ...


type Identify = Callable[[str], EngineIdentity | None]


@dataclass(frozen=True, slots=True)
class Engine:
    """A reachable engine: its client, the `ID` of `/info` and the socket it was reached on."""

    client: Any
    engine_id: str
    identity: EngineIdentity


@dataclass(frozen=True, slots=True)
class EngineView:
    """The engines usable right now, and what is wrong with the others."""

    engines: tuple[Engine, ...]
    notices: tuple[EngineNotice, ...]


class EngineProvider(Protocol):
    def refresh(self) -> EngineView:
        """Resolve the endpoints again and return the engines that answer."""
        ...

    def discard(self, *, engine: Engine) -> None:
        """Forget the engine's client: the next refresh connects again."""
        ...


def identity_of(*, path: str) -> EngineIdentity | None:
    """The socket's path with its inode and device, or None if it cannot be statted."""
    try:
        info = os.stat(path)
    except OSError as error:
        LOGGER.debug("Cannot stat engine socket %s: %s", path, error)
        return None
    return EngineIdentity(path=path, st_ino=info.st_ino, st_dev=info.st_dev)


def connect_client(*, found: DockerEndpoint, timeout: int) -> Any:
    """A client on the endpoint's unix socket; it does not connect until it is used."""
    return docker.DockerClient(base_url=UNIX_PREFIX + found.path, timeout=timeout)


def local_resolution() -> EndpointResolution:
    """The endpoints of this machine, from the real environment and home."""
    return resolve_local_docker_endpoints(environ=os.environ, home=Path.home())


def local_engine_identities() -> tuple[EngineIdentity, ...]:
    """Identity of every resolved engine socket, without connecting to any (S9)."""
    found = (identity_of(path=item.path) for item in local_resolution().endpoints)
    return tuple(identity for identity in found if identity is not None)


def _close(*, client: Any) -> None:
    try:
        client.close()
    except Exception as error:
        LOGGER.debug("Cannot close the engine client: %r", error)


@dataclass(frozen=True, slots=True)
class _Backoff:
    """When an endpoint may be contacted again, the delay that follows a new failure, and why."""

    retry_at: float
    delay: float
    detail: str


class EnginePool:
    """Clients for the resolved endpoints, reused while the socket is the same file.

    Not thread-safe: each consumer (the sampler, the executor) owns its pool. Two sockets
    that reach the same engine (podman-docker) count once, by the `ID` of `/info`; the first
    in resolution order wins. An endpoint that does not answer is not contacted again for a
    delay that doubles from `BACKOFF_INITIAL_S` to `BACKOFF_MAX_S`: a socket that hangs would
    otherwise cost the whole timeout in every sampling cycle (RNF-03). The delay restarts when
    the socket's identity changes or the endpoint answers.
    """

    def __init__(
        self,
        *,
        resolve: Callable[[], EndpointResolution],
        connect: Connect,
        identify: Identify | None = None,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._resolve = resolve
        self._connect = connect
        self._identify: Identify = identify or (lambda path: identity_of(path=path))
        self._clock = clock
        self._known: dict[EngineIdentity, Engine] = {}
        self._backoff: dict[EngineIdentity, _Backoff] = {}

    def refresh(self) -> EngineView:
        resolution = self._resolve()
        notices = [rejection_notice(rejected=item) for item in resolution.rejected]
        current: dict[EngineIdentity, Engine] = {}
        seen: set[EngineIdentity] = set()
        for found in resolution.endpoints:
            engine = self._engine_for(found=found, notices=notices, seen=seen)
            if engine is not None:
                current[engine.identity] = engine
        self._backoff = {key: value for key, value in self._backoff.items() if key in seen}
        for identity, engine in self._known.items():
            if identity not in current:
                _close(client=engine.client)
        self._known = current
        return EngineView(
            engines=_distinct(engines=tuple(current.values())), notices=tuple(notices)
        )

    def discard(self, *, engine: Engine) -> None:
        if self._known.pop(engine.identity, None) is not None:
            _close(client=engine.client)

    def _engine_for(
        self, *, found: DockerEndpoint, notices: list[EngineNotice], seen: set[EngineIdentity]
    ) -> Engine | None:
        identity = self._identify(found.path)
        if identity is None:
            notices.append(_unreachable(path=found.path, detail="socket not found"))
            return None
        seen.add(identity)
        known = self._known.get(identity)
        if known is not None:
            return known
        waiting = self._backoff.get(identity)
        if waiting is not None and self._clock() < waiting.retry_at:
            notices.append(_unreachable(path=found.path, detail=waiting.detail))
            return None
        return self._open(found=found, identity=identity, notices=notices)

    def _open(
        self, *, found: DockerEndpoint, identity: EngineIdentity, notices: list[EngineNotice]
    ) -> Engine | None:
        client = None
        try:
            client = self._connect(found=found)
            engine_id = str(client.info().get(ENGINE_ID_KEY) or found.path)
        except Exception as error:
            LOGGER.debug("Engine on %s is not answering: %r", found.path, error)
            if client is not None:
                _close(client=client)
            detail = str(error) or type(error).__name__
            self._record_failure(identity=identity, detail=detail)
            notices.append(_unreachable(path=found.path, detail=detail))
            return None
        self._backoff.pop(identity, None)
        return Engine(client=client, engine_id=engine_id, identity=identity)

    def _record_failure(self, *, identity: EngineIdentity, detail: str) -> None:
        previous = self._backoff.get(identity)
        delay = (
            BACKOFF_INITIAL_S
            if previous is None
            else min(previous.delay * BACKOFF_FACTOR, BACKOFF_MAX_S)
        )
        self._backoff[identity] = _Backoff(
            retry_at=self._clock() + delay, delay=delay, detail=detail
        )


def _unreachable(*, path: str, detail: str) -> EngineNotice:
    return EngineNotice(code=NoticeCode.UNREACHABLE, endpoint=path, detail=detail)


def _distinct(*, engines: tuple[Engine, ...]) -> tuple[Engine, ...]:
    seen: set[str] = set()
    kept = []
    for engine in engines:
        if engine.engine_id not in seen:
            seen.add(engine.engine_id)
            kept.append(engine)
    return tuple(kept)


class FixedEngines:
    """One client that is always the engine: for tests and for an injected reader."""

    def __init__(self, *, client: Any, path: str = FIXED_ENGINE_PATH) -> None:
        identity = EngineIdentity(path=path, st_ino=0, st_dev=0)
        self._view = EngineView(
            engines=(Engine(client=client, engine_id=path, identity=identity),), notices=()
        )

    def refresh(self) -> EngineView:
        return self._view

    def discard(self, *, engine: Engine) -> None:
        return None


def local_pool(*, timeout: int) -> EnginePool:
    """A pool on this machine's real endpoints; nothing is read until `refresh`."""
    return EnginePool(
        resolve=local_resolution, connect=lambda found: connect_client(found=found, timeout=timeout)
    )
