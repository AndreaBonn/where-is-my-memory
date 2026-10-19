from collections.abc import Callable
from typing import Any

from wimm.collectors.docker_engines import (
    EnginePool,
)
from wimm.core.docker_endpoint import (
    DockerEndpoint,
    EndpointResolution,
    EndpointSource,
    RejectedEndpoint,
)
from wimm.model.actions import EngineIdentity

DOCKER = "/var/run/docker.sock"
PODMAN = "/run/user/1000/podman/podman.sock"
THREADS = 8


class FakeClient:
    def __init__(self, engine_id: str, failure: Exception | None = None) -> None:
        self.engine_id = engine_id
        self.failure = failure
        self.closed = False
        self.close_calls = 0
        self.info_calls = 0

    def info(self) -> dict[str, Any]:
        self.info_calls += 1
        if self.failure is not None:
            raise self.failure
        return {"ID": self.engine_id}

    def close(self) -> None:
        self.closed = True
        self.close_calls += 1


def endpoint(path: str, source: EndpointSource = EndpointSource.DEFAULT_SOCKET) -> DockerEndpoint:
    return DockerEndpoint(source=source, url="unix://" + path, path=path, realpath=path)


def identities(inodes: dict[str, int]) -> Callable[[str], EngineIdentity | None]:
    def identify(path: str) -> EngineIdentity | None:
        if path not in inodes:
            return None
        return EngineIdentity(path=path, st_ino=inodes[path], st_dev=1)

    return identify


class Rig:
    """A pool wired to fakes: what the resolver returns, which client each socket gives."""

    def __init__(self, clients: dict[str, FakeClient], paths: tuple[str, ...]) -> None:
        self.clients = clients
        self.paths = paths
        self.rejected: tuple[RejectedEndpoint, ...] = ()
        self.inodes = {path: 10 + index for index, path in enumerate(paths)}
        self.connects: list[str] = []
        self.now = 1000.0
        self.pool = EnginePool(
            resolve=self.resolve,
            connect=self.connect,
            identify=self.identify,
            clock=lambda: self.now,
        )

    def resolve(self) -> EndpointResolution:
        return EndpointResolution(
            endpoints=tuple(endpoint(path) for path in self.paths), rejected=self.rejected
        )

    def connect(self, found: DockerEndpoint) -> FakeClient:
        self.connects.append(found.path)
        return self.clients[found.path]

    def identify(self, path: str) -> EngineIdentity | None:
        return identities(self.inodes)(path)
