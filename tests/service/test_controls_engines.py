from dataclasses import dataclass, field

import docker.errors
import pytest

from tests.service.engine_fakes import FakeProvider, engine_at
from wimm.service.controls import DockerSdkControl
from wimm.service.errors import ControlFailed, DockerUnavailable

DOCKER_SOCKET = "/var/run/docker.sock"
PODMAN_SOCKET = "/run/user/1000/podman/podman.sock"


@dataclass(slots=True)
class FakeContainer:
    id: str
    status: str = "running"
    calls: list[str] = field(default_factory=list)

    def stop(self, *, timeout: int) -> None:
        self.calls.append(f"stop:{timeout}")

    def start(self) -> None:
        self.calls.append("start")

    def remove(self, *, v: bool) -> None:
        self.calls.append(f"remove:{v}")


@dataclass(slots=True)
class FakeContainers:
    held: dict[str, FakeContainer] = field(default_factory=dict)
    error: Exception | None = None
    asked: list[str] = field(default_factory=list)

    def get(self, container_id: str) -> FakeContainer:
        self.asked.append(container_id)
        if self.error is not None:
            raise self.error
        if container_id not in self.held:
            raise docker.errors.NotFound("no such container")
        return self.held[container_id]


@dataclass(slots=True)
class FakeClient:
    containers: FakeContainers = field(default_factory=FakeContainers)


def _client(*held: FakeContainer, error: Exception | None = None) -> FakeClient:
    return FakeClient(containers=FakeContainers(held={item.id: item for item in held}, error=error))


def _control(*clients: FakeClient) -> DockerSdkControl:
    paths = (DOCKER_SOCKET, PODMAN_SOCKET)
    engines = tuple(engine_at(path=paths[i], client=c) for i, c in enumerate(clients))
    return DockerSdkControl(engines=FakeProvider(engines=engines))


def test_construction_does_no_engine_io() -> None:
    provider = FakeProvider(engines=())

    DockerSdkControl(engines=provider)

    assert provider.refreshes == 0


def test_stop_goes_to_the_engine_that_holds_the_container() -> None:
    mine = FakeContainer(id="c2")
    first, second = _client(FakeContainer(id="c1")), _client(mine)

    _control(first, second).stop(container_id="c2", timeout_s=7)

    assert mine.calls == ["stop:7"]
    assert first.containers.asked == ["c2"]  # the other engine was asked first, and said no


def test_the_first_engine_that_has_the_id_wins() -> None:
    a, b = FakeContainer(id="c1"), FakeContainer(id="c1")

    _control(_client(a), _client(b)).remove(container_id="c1", volumes=True)

    assert a.calls == ["remove:True"] and b.calls == []


def test_inspect_reads_the_status_from_the_holding_engine() -> None:
    live = _control(_client(), _client(FakeContainer(id="c9", status="exited"))).inspect(
        container_id="c9"
    )

    assert live is not None and live.status == "exited"


def test_unknown_container_on_every_engine_is_not_found_as_before() -> None:
    control = _control(_client(), _client())

    assert control.inspect(container_id="ghost") is None
    control.stop(container_id="ghost", timeout_s=1)
    control.start(container_id="ghost")
    control.remove(container_id="ghost", volumes=False)


def test_a_failing_engine_is_a_control_failure_not_a_missing_container() -> None:
    broken = _client(error=docker.errors.APIError("daemon down"))

    with pytest.raises(ControlFailed, match="daemon down"):
        _control(broken, _client(FakeContainer(id="c1"))).inspect(container_id="c1")


def test_no_engine_at_all_is_docker_unavailable() -> None:
    with pytest.raises(DockerUnavailable):
        _control().stop(container_id="c1", timeout_s=1)


def test_engines_are_resolved_again_for_every_operation() -> None:
    provider = FakeProvider(engines=(engine_at(path=DOCKER_SOCKET, client=_client()),))
    control = DockerSdkControl(engines=provider)

    control.inspect(container_id="a")
    control.inspect(container_id="b")

    assert provider.refreshes == 2
