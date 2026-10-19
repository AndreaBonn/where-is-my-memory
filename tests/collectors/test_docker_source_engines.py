import logging
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import docker
import docker.errors
import pytest

from wimm.collectors import docker_engines, docker_stats
from wimm.collectors.docker_engines import Engine, EngineView
from wimm.collectors.docker_source import DockerReader, DockerSource
from wimm.core.docker_endpoint import (
    DockerEndpoint,
    EndpointResolution,
    EndpointSource,
    RejectedEndpoint,
    RejectionReason,
)
from wimm.core.docker_notices import EngineNotice, NoticeCode
from wimm.model.actions import EngineIdentity
from wimm.model.enums import MetricsSource
from wimm.model.raw import RawContainer

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


def test_containers_of_every_engine_are_collected_in_engine_order(tmp_path: Path) -> None:
    docker_client = FakeEngineClient([FakeContainer("d1", state="exited")])
    podman_client = FakeEngineClient([FakeContainer("p1", state="exited")])
    engines = FakeEngines(
        [engine(DOCKER, docker_client, "docker-id"), engine(PODMAN, podman_client, "podman-id")]
    )
    result = source_of(engines, tmp_path).collect()
    assert result.data.status.available
    assert [item.id for item in result.data.containers] == ["d1", "p1"]
    assert result.data.notices == ()


def test_a_failing_engine_does_not_block_the_others_and_leaves_a_notice(tmp_path: Path) -> None:
    good = FakeEngineClient([FakeContainer("d1", state="exited")])
    broken = FakeEngineClient(failure="connection reset")
    engines = FakeEngines([engine(DOCKER, good, "a"), engine(PODMAN, broken, "b")])
    result = source_of(engines, tmp_path).collect()
    assert result.error is None
    assert result.data.status.available
    assert [item.id for item in result.data.containers] == ["d1"]
    (notice,) = result.data.notices
    assert (notice.code, notice.endpoint) == (NoticeCode.UNREACHABLE, PODMAN)
    assert "connection reset" in notice.detail
    assert [item.identity.path for item in engines.discarded] == [PODMAN]


def test_all_engines_failing_is_unavailable_with_one_message_per_engine(tmp_path: Path) -> None:
    engines = FakeEngines(
        [
            engine(DOCKER, FakeEngineClient(failure="first down"), "a"),
            engine(PODMAN, FakeEngineClient(failure="second down"), "b"),
        ]
    )
    result = source_of(engines, tmp_path).collect()
    assert result.data.status.available is False
    error = result.data.status.error or ""
    assert "first down" in error and "second down" in error
    assert result.error == error


def test_rejected_endpoints_with_no_engine_left_are_the_message(tmp_path: Path) -> None:
    rejected = EngineNotice(code=NoticeCode.UNSUPPORTED_SCHEME, endpoint="tcp://203.0.113.9:2375")
    result = source_of(FakeEngines([], [rejected]), tmp_path).collect()
    assert result.data.status.available is False
    assert "tcp://203.0.113.9:2375" in (result.data.status.error or "")


def test_no_endpoint_at_all_keeps_the_docker_non_disponibile_reason(tmp_path: Path) -> None:
    result = source_of(FakeEngines([]), tmp_path).collect()
    assert (result.data.status.available, result.data.status.error) == (
        False,
        "nessun socket Docker o Podman trovato",
    )


def test_a_rejected_endpoint_next_to_a_working_one_is_only_a_notice(tmp_path: Path) -> None:
    rejected = EngineNotice(code=NoticeCode.UNSUPPORTED_SCHEME, endpoint="tcp://203.0.113.9:2375")
    client = FakeEngineClient([FakeContainer("d1", state="exited")])
    result = source_of(FakeEngines([engine(DOCKER, client, "a")], [rejected]), tmp_path).collect()
    assert result.data.status.available
    assert result.data.notices == (rejected,)


def test_partial_failures_warn_once_per_change(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    broken = FakeEngineClient(failure="down")
    engines = FakeEngines(
        [engine(DOCKER, FakeEngineClient(), "a"), engine(PODMAN, broken, "b")],
        [EngineNotice(code=NoticeCode.UNSUPPORTED_SCHEME, endpoint="tcp://x")],
    )
    source = source_of(engines, tmp_path)
    with caplog.at_level(level=logging.WARNING):
        source.collect()
        source.collect()
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "tcp://x" in warnings[0].getMessage()


def test_an_engine_that_comes_back_is_collected_again(tmp_path: Path) -> None:
    client = FakeEngineClient([FakeContainer("p1", state="exited")], failure="down")
    source = source_of(FakeEngines([engine(PODMAN, client, "b")]), tmp_path)
    assert source.collect().data.status.available is False
    client.failure = None
    assert [item.id for item in source.collect().data.containers] == ["p1"]


def test_nothing_is_resolved_before_the_first_collect(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden() -> EndpointResolution:
        raise AssertionError("resolved at construction")

    monkeypatch.setattr(target=docker_engines, name="local_resolution", value=forbidden)
    DockerSource()


def test_the_default_source_connects_to_resolved_sockets_never_from_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    built: list[str] = []
    client = FakeEngineClient([FakeContainer("d1", state="exited")])

    def build(**kwargs: Any) -> FakeEngineClient:
        built.append(kwargs["base_url"])
        return client

    def forbidden(**kwargs: Any) -> None:
        raise AssertionError("from_env")

    found = DockerEndpoint(
        source=EndpointSource.DEFAULT_SOCKET, url="unix://" + DOCKER, path=DOCKER, realpath=DOCKER
    )
    resolution = EndpointResolution(
        endpoints=(found,),
        rejected=(
            RejectedEndpoint(
                source=EndpointSource.DOCKER_HOST,
                endpoint="tcp://203.0.113.9:2375",
                reason=RejectionReason.UNSUPPORTED_SCHEME,
            ),
        ),
    )
    monkeypatch.setattr(target=docker, name="DockerClient", value=build)
    monkeypatch.setattr(target=docker, name="from_env", value=forbidden)
    monkeypatch.setattr(target=docker_engines, name="local_resolution", value=lambda: resolution)
    monkeypatch.setattr(
        target=docker_engines,
        name="identity_of",
        value=lambda *, path: EngineIdentity(path=path, st_ino=1, st_dev=1),
    )
    result = DockerSource(roots=(tmp_path, tmp_path)).collect()
    assert built == ["unix://" + DOCKER]
    assert [item.id for item in result.data.containers] == ["d1"]
    assert [notice.code for notice in result.data.notices] == [NoticeCode.UNSUPPORTED_SCHEME]


def test_a_reader_is_a_single_engine(tmp_path: Path) -> None:
    client = FakeEngineClient([FakeContainer("d1", state="exited")])
    source = DockerSource(reader=cast(DockerReader, client), roots=(tmp_path, tmp_path))
    result = source.collect()
    assert [item.id for item in result.data.containers] == ["d1"]


def running(count: int) -> list[FakeContainer]:
    return [FakeContainer(f"c{index:02d}") for index in range(count)]


def test_stats_are_read_for_a_few_containers_per_cycle_and_rotate(tmp_path: Path) -> None:
    containers = running(10)
    client = FakeEngineClient(containers)
    source = source_of(FakeEngines([engine(DOCKER, client, "a")]), tmp_path)
    limit = docker_stats.STATS_MAX_PER_CYCLE

    first = source.collect().data.containers
    assert sum(item.metrics_source is MetricsSource.STATS_API for item in first) == limit
    assert sum(c.calls for c in containers) == limit

    second = source.collect().data.containers
    sampled = [item.id for item in second if item.metrics_source is MetricsSource.STATS_API]
    assert len(sampled) == 2 * limit
    assert all(c.calls <= 1 for c in containers)

    for _ in range(3):
        source.collect()
    final = source.collect().data.containers
    assert all(item.metrics_source is MetricsSource.STATS_API for item in final)
    assert all(c.calls == 1 for c in containers)


def test_a_container_without_a_reading_yet_is_unavailable_not_zero(tmp_path: Path) -> None:
    containers = running(docker_stats.STATS_MAX_PER_CYCLE + 1)
    source = source_of(FakeEngines([engine(DOCKER, FakeEngineClient(containers), "a")]), tmp_path)
    waiting = [
        item
        for item in source.collect().data.containers
        if item.metrics_source is MetricsSource.UNAVAILABLE
    ]
    assert len(waiting) == 1
    assert (waiting[0].memory_bytes, waiting[0].net_bytes) == (0, None)


def test_a_slow_stats_call_does_not_hold_the_cycle_and_lands_in_the_next_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(target=docker_stats, name="STATS_BUDGET_S", value=0.05)
    slow = FakeContainer("slow")
    slow.gate = threading.Event()
    source = source_of(FakeEngines([engine(DOCKER, FakeEngineClient([slow]), "a")]), tmp_path)

    started = time.monotonic()
    (first,) = source.collect().data.containers
    assert time.monotonic() - started < 2
    assert first.metrics_source is MetricsSource.UNAVAILABLE

    slow.gate.set()
    second = _collect_until_stats(source=source)
    assert second.metrics_source is MetricsSource.STATS_API
    assert second.memory_bytes == 70
    assert slow.calls == 1


def test_a_call_still_running_is_not_started_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(target=docker_stats, name="STATS_BUDGET_S", value=0.02)
    slow = FakeContainer("slow")
    slow.gate = threading.Event()
    source = source_of(FakeEngines([engine(DOCKER, FakeEngineClient([slow]), "a")]), tmp_path)
    source.collect()
    source.collect()
    slow.gate.set()
    _collect_until_stats(source=source)
    assert slow.calls == 1


def test_cycle_duration_is_logged_at_debug(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    source = source_of(FakeEngines([engine(DOCKER, FakeEngineClient(running(2)), "a")]), tmp_path)
    with caplog.at_level(level=logging.DEBUG, logger="wimm.collectors.docker_source"):
        source.collect()
    (line,) = [r.getMessage() for r in caplog.records if "Docker sample" in r.getMessage()]
    assert "2 containers" in line and " s" in line


def _collect_until_stats(*, source: DockerSource, timeout_s: float = 5.0) -> RawContainer:
    """Collect until the background stats call has landed; a collect never starts a second one."""
    deadline = time.monotonic() + timeout_s
    while True:
        (item,) = source.collect().data.containers
        if item.metrics_source is MetricsSource.STATS_API:
            return item
        assert time.monotonic() < deadline, "stats call never landed"
        time.sleep(0.01)


class StallingClient(FakeEngineClient):
    """An engine whose socket exists but never answers: `info()` ends in the client timeout."""

    def __init__(self) -> None:
        super().__init__()
        self.info_calls = 0

    def info(self) -> dict[str, str]:
        self.info_calls += 1
        raise TimeoutError("timed out")


def test_a_stalling_engine_is_not_asked_again_during_backoff_and_does_not_hide_the_healthy_one(
    tmp_path: Path,
) -> None:
    stalling = StallingClient()
    healthy = FakeEngineClient([FakeContainer("d1", state="exited")])
    clients = {PODMAN: stalling, DOCKER: healthy}
    now = [1000.0]

    def resolve() -> EndpointResolution:
        return EndpointResolution(
            endpoints=tuple(
                DockerEndpoint(
                    source=EndpointSource.DEFAULT_SOCKET, url="unix://" + p, path=p, realpath=p
                )
                for p in (PODMAN, DOCKER)
            ),
            rejected=(),
        )

    pool = docker_engines.EnginePool(
        resolve=resolve,
        connect=lambda found: clients[found.path],
        identify=lambda path: EngineIdentity(path=path, st_ino=1, st_dev=1),
        clock=lambda: now[0],
    )
    source = DockerSource(roots=(tmp_path, tmp_path), engines=pool)

    first = source.collect()
    second = source.collect()
    assert stalling.info_calls == 1
    for result in (first, second):
        assert [item.id for item in result.data.containers] == ["d1"]
        (notice,) = result.data.notices
        assert (notice.code, notice.endpoint) == (NoticeCode.UNREACHABLE, PODMAN)

    now[0] += docker_engines.BACKOFF_INITIAL_S
    source.collect()
    assert stalling.info_calls == 2
