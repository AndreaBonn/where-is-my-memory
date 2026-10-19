import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import docker
import docker.errors

from wimm.collectors.docker_engines import Engine, EngineView
from wimm.collectors.docker_source import DockerSource
from wimm.core.docker_notices import EngineNotice
from wimm.model.actions import EngineIdentity

DOCKER = "/var/run/docker.sock"
PODMAN = "/run/user/1000/podman/podman.sock"


class FakeContainer:
    def __init__(self, identifier: str, state: str = "running") -> None:
        self.id = identifier
        self.attrs: dict[str, Any] = {
            "Name": f"/{identifier}",
            "Config": {"Image": "image:tag", "Labels": {}},
            "State": {"Status": state, "Pid": 0},
        }
        self.calls = 0
        self.gate: threading.Event | None = None

    def stats(self, stream: bool) -> dict[str, Any]:
        assert stream is False
        self.calls += 1
        if self.gate is not None:
            self.gate.wait(timeout=5)
        return {"memory_stats": {"usage": 100, "stats": {"inactive_file": 30}}}


class FakeEngineClient:
    def __init__(self, containers: Sequence[FakeContainer] = (), failure: str | None = None):
        self.items = list(containers)
        self.failure = failure
        self.containers = self

    def info(self) -> dict[str, str]:
        return {"ID": "docker-id"}

    def list(self, *, all: bool, ignore_removed: bool) -> Sequence[FakeContainer]:
        assert all is True and ignore_removed is True
        if self.failure is not None:
            raise docker.errors.DockerException(self.failure)
        return self.items


def engine(path: str, client: FakeEngineClient, engine_id: str) -> Engine:
    return Engine(
        client=client, engine_id=engine_id, identity=EngineIdentity(path=path, st_ino=1, st_dev=1)
    )


class FakeEngines:
    def __init__(self, engines: Sequence[Engine], notices: Sequence[EngineNotice] = ()) -> None:
        self.view = EngineView(engines=tuple(engines), notices=tuple(notices))
        self.discarded: list[Engine] = []

    def refresh(self) -> EngineView:
        return self.view

    def discard(self, *, engine: Engine) -> None:
        self.discarded.append(engine)


def source_of(engines: FakeEngines, tmp_path: Path) -> DockerSource:
    return DockerSource(roots=(tmp_path, tmp_path), engines=engines)
