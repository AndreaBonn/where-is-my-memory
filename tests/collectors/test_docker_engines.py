import os
import socket
from collections.abc import Callable
from pathlib import Path
from typing import Any

import docker
import docker.errors
import pytest

from wimm.collectors import docker_engines
from wimm.collectors.docker_engines import (
    EnginePool,
    FixedEngines,
    connect_client,
    identity_of,
    local_engine_identities,
)
from wimm.core.docker_endpoint import (
    DockerEndpoint,
    EndpointResolution,
    EndpointSource,
    RejectedEndpoint,
    RejectionReason,
)
from wimm.core.docker_notices import NoticeCode
from wimm.model.actions import EngineIdentity

DOCKER = "/var/run/docker.sock"
PODMAN = "/run/user/1000/podman/podman.sock"


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


def test_connect_client_builds_the_client_on_the_unix_socket_not_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[dict[str, Any]] = []

    def build(**kwargs: Any) -> str:
        seen.append(kwargs)
        return "client"

    def forbidden(**kwargs: Any) -> None:
        raise AssertionError("docker.from_env follows an unvalidated DOCKER_HOST")

    monkeypatch.setattr(target=docker, name="DockerClient", value=build)
    monkeypatch.setattr(target=docker, name="from_env", value=forbidden)
    monkeypatch.setenv(name="DOCKER_HOST", value="tcp://203.0.113.9:2375")

    assert connect_client(found=endpoint(PODMAN), timeout=7) == "client"
    assert seen == [{"base_url": "unix://" + PODMAN, "timeout": 7}]


def test_refresh_gives_one_engine_per_endpoint_in_resolution_order() -> None:
    rig = Rig({DOCKER: FakeClient("docker-id"), PODMAN: FakeClient("podman-id")}, (DOCKER, PODMAN))
    view = rig.pool.refresh()
    assert [engine.engine_id for engine in view.engines] == ["docker-id", "podman-id"]
    assert [engine.identity.path for engine in view.engines] == [DOCKER, PODMAN]
    assert view.notices == ()


def test_two_sockets_of_the_same_engine_are_one_engine_the_first_wins() -> None:
    shared = FakeClient("same-id")
    rig = Rig({DOCKER: shared, PODMAN: FakeClient("same-id")}, (DOCKER, PODMAN))
    view = rig.pool.refresh()
    assert len(view.engines) == 1
    assert view.engines[0].identity.path == DOCKER
    assert view.engines[0].client is shared


def test_an_unreachable_endpoint_is_a_notice_and_does_not_block_the_others() -> None:
    broken = FakeClient("x", failure=docker.errors.DockerException("connection refused"))
    rig = Rig({DOCKER: FakeClient("docker-id"), PODMAN: broken}, (DOCKER, PODMAN))
    view = rig.pool.refresh()
    assert [engine.engine_id for engine in view.engines] == ["docker-id"]
    (notice,) = view.notices
    assert (notice.code, notice.endpoint) == (NoticeCode.UNREACHABLE, PODMAN)
    assert "connection refused" in notice.detail


def test_an_unreachable_endpoint_is_retried_once_the_backoff_has_elapsed() -> None:
    client = FakeClient("podman-id", failure=OSError("refused"))
    rig = Rig({PODMAN: client}, (PODMAN,))
    assert rig.pool.refresh().engines == ()
    client.failure = None
    rig.now += docker_engines.BACKOFF_INITIAL_S
    assert [engine.engine_id for engine in rig.pool.refresh().engines] == ["podman-id"]
    assert rig.connects == [PODMAN, PODMAN]


def test_an_endpoint_in_backoff_is_not_contacted_and_still_gives_the_notice() -> None:
    slow = FakeClient("slow", failure=TimeoutError("timed out"))
    rig = Rig({DOCKER: FakeClient("docker-id"), PODMAN: slow}, (PODMAN, DOCKER))
    rig.pool.refresh()
    rig.now += docker_engines.BACKOFF_INITIAL_S - 1
    view = rig.pool.refresh()
    assert slow.info_calls == 1
    assert rig.connects == [PODMAN, DOCKER]
    assert [engine.engine_id for engine in view.engines] == ["docker-id"]
    (notice,) = view.notices
    assert (notice.code, notice.endpoint) == (NoticeCode.UNREACHABLE, PODMAN)
    assert "timed out" in notice.detail


def test_the_backoff_doubles_up_to_the_ceiling() -> None:
    slow = FakeClient("slow", failure=TimeoutError("timed out"))
    rig = Rig({PODMAN: slow}, (PODMAN,))
    delay = docker_engines.BACKOFF_INITIAL_S
    for expected_calls in range(1, 13):
        rig.pool.refresh()
        assert slow.info_calls == expected_calls
        rig.now += delay - 1
        rig.pool.refresh()
        assert slow.info_calls == expected_calls
        rig.now += 1
        delay = min(delay * 2, docker_engines.BACKOFF_MAX_S)
    assert delay == docker_engines.BACKOFF_MAX_S


def test_a_recovered_endpoint_starts_over_from_the_initial_backoff() -> None:
    client = FakeClient("podman-id", failure=OSError("refused"))
    rig = Rig({PODMAN: client}, (PODMAN,))
    rig.pool.refresh()
    rig.now += docker_engines.BACKOFF_INITIAL_S
    rig.pool.refresh()
    rig.now += docker_engines.BACKOFF_INITIAL_S * 2
    client.failure = None
    (engine,) = rig.pool.refresh().engines
    rig.pool.discard(engine=engine)
    client.failure = OSError("refused again")
    rig.pool.refresh()
    rig.now += docker_engines.BACKOFF_INITIAL_S
    client.failure = None
    assert len(rig.pool.refresh().engines) == 1


def test_a_socket_recreated_with_another_inode_skips_the_backoff() -> None:
    client = FakeClient("docker-id", failure=OSError("refused"))
    rig = Rig({DOCKER: client}, (DOCKER,))
    rig.pool.refresh()
    client.failure = None
    rig.inodes[DOCKER] += 100
    assert len(rig.pool.refresh().engines) == 1


def test_a_client_whose_info_fails_is_closed() -> None:
    client = FakeClient("x", failure=TimeoutError("timed out"))
    rig = Rig({PODMAN: client}, (PODMAN,))
    rig.pool.refresh()
    assert client.close_calls == 1


def test_rejected_endpoints_become_notices_with_the_reason() -> None:
    rig = Rig({DOCKER: FakeClient("docker-id")}, (DOCKER,))
    rig.rejected = (
        RejectedEndpoint(
            source=EndpointSource.DOCKER_HOST,
            endpoint="tcp://203.0.113.9:2375",
            reason=RejectionReason.UNSUPPORTED_SCHEME,
        ),
    )
    view = rig.pool.refresh()
    assert len(view.engines) == 1
    (notice,) = view.notices
    assert notice.code is NoticeCode.UNSUPPORTED_SCHEME
    assert notice.endpoint == "tcp://203.0.113.9:2375"


def test_a_socket_that_vanished_between_resolution_and_connection_is_a_notice() -> None:
    rig = Rig({DOCKER: FakeClient("docker-id")}, (DOCKER,))
    rig.inodes.clear()
    view = rig.pool.refresh()
    assert view.engines == ()
    assert [notice.code for notice in view.notices] == [NoticeCode.UNREACHABLE]


def test_clients_are_reused_while_the_socket_is_the_same_file() -> None:
    rig = Rig({DOCKER: FakeClient("docker-id")}, (DOCKER,))
    first = rig.pool.refresh().engines[0]
    second = rig.pool.refresh().engines[0]
    assert second.client is first.client
    assert rig.connects == [DOCKER]


def test_a_socket_recreated_with_another_inode_gets_a_new_client_and_closes_the_old() -> None:
    old, new = FakeClient("docker-id"), FakeClient("docker-id")
    rig = Rig({DOCKER: old}, (DOCKER,))
    rig.pool.refresh()
    rig.clients[DOCKER] = new
    rig.inodes[DOCKER] += 100
    engine = rig.pool.refresh().engines[0]
    assert engine.client is new
    assert old.closed is True and new.closed is False


def test_an_endpoint_that_disappears_from_the_resolution_is_released() -> None:
    podman = FakeClient("podman-id")
    rig = Rig({DOCKER: FakeClient("docker-id"), PODMAN: podman}, (DOCKER, PODMAN))
    assert len(rig.pool.refresh().engines) == 2
    rig.paths = (DOCKER,)
    assert len(rig.pool.refresh().engines) == 1
    assert podman.closed is True


def test_discard_forces_a_new_connection_at_the_next_refresh() -> None:
    rig = Rig({DOCKER: FakeClient("docker-id")}, (DOCKER,))
    engine = rig.pool.refresh().engines[0]
    rig.pool.discard(engine=engine)
    rig.pool.refresh()
    assert rig.connects == [DOCKER, DOCKER]


def test_the_duplicate_stays_known_so_its_info_is_not_asked_again() -> None:
    rig = Rig({DOCKER: FakeClient("same"), PODMAN: FakeClient("same")}, (DOCKER, PODMAN))
    rig.pool.refresh()
    rig.pool.refresh()
    assert rig.connects == [DOCKER, PODMAN]


def test_an_engine_without_id_is_identified_by_its_path() -> None:
    first, second = FakeClient(""), FakeClient("")
    rig = Rig({DOCKER: first, PODMAN: second}, (DOCKER, PODMAN))
    assert len(rig.pool.refresh().engines) == 2


def test_fixed_engines_wrap_one_client() -> None:
    client = FakeClient("only")
    view = FixedEngines(client=client).refresh()
    assert [engine.client for engine in view.engines] == [client]
    assert view.notices == ()


def test_identity_of_reports_inode_and_device_of_the_socket_file(tmp_path: Path) -> None:
    path = tmp_path / "engine.sock"
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(str(path))
        info = os.stat(path)
        assert identity_of(path=str(path)) == EngineIdentity(
            path=str(path), st_ino=info.st_ino, st_dev=info.st_dev
        )
    assert identity_of(path=str(tmp_path / "missing.sock")) is None


def test_local_engine_identities_follow_the_resolved_endpoints(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    present = tmp_path / "a.sock"
    present.write_text("")
    resolution = EndpointResolution(
        endpoints=(endpoint(str(present)), endpoint(str(tmp_path / "gone.sock"))), rejected=()
    )
    monkeypatch.setattr(target=docker_engines, name="local_resolution", value=lambda: resolution)
    (only,) = local_engine_identities()
    assert only.path == str(present)
