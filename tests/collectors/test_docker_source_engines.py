import logging
from pathlib import Path
from typing import Any, cast

import docker
import docker.errors
import pytest

from tests.collectors.docker_source_engines_helpers import (
    DOCKER,
    PODMAN,
    FakeContainer,
    FakeEngineClient,
    FakeEngines,
    engine,
    source_of,
)
from wimm.collectors import docker_engines
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
