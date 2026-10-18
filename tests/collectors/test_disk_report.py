import json
from pathlib import Path
from typing import Any

import docker.errors
import pytest
import requests

from tests.service.engine_fakes import FakeProvider, engine_at
from wimm.collectors import disk_report
from wimm.collectors.disk_report import DF_TIMEOUT_S, NO_ENGINE, DockerDiskSource
from wimm.collectors.docker_engines import FixedEngines
from wimm.core.disk_rules import parse_docker_df

FIXTURE = Path(__file__).parent.parent / "fixtures" / "docker_df.json"


class FakeApi:
    def __init__(self, *, answer: Any = None, failure: Exception | None = None) -> None:
        self.answer, self.failure, self.calls = answer, failure, 0

    def df(self) -> Any:
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        return self.answer


class FakeClient:
    def __init__(self, *, api: FakeApi) -> None:
        self.api = api


def _source(*, api: FakeApi) -> DockerDiskSource:
    return DockerDiskSource(engines=FixedEngines(client=FakeClient(api=api)))


def test_collect_fixture_returns_parsed_docker_disk() -> None:
    raw = json.loads(FIXTURE.read_text())
    result = _source(api=FakeApi(answer=raw)).collect()
    assert result.error is None
    assert result.data == parse_docker_df(df=raw)
    assert result.data.status.available is True
    assert result.data.images


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (docker.errors.DockerException("Error while fetching server API version"), "fetching"),
        (docker.errors.APIError("permission denied"), "permission denied"),
        (requests.exceptions.ReadTimeout("read timed out"), "timed out"),
        (requests.exceptions.ConnectionError("connection refused"), "refused"),
        (PermissionError("socket"), "socket"),
    ],
)
def test_collect_failure_returns_unavailable_with_message(
    failure: Exception, expected: str
) -> None:
    result = _source(api=FakeApi(failure=failure)).collect()
    assert result.data.status.available is False
    assert expected in (result.data.status.error or "")
    assert result.error == result.data.status.error
    assert result.data.images == ()


def test_collect_unexpected_answer_returns_unavailable() -> None:
    result = _source(api=FakeApi(answer=["not", "a", "mapping"])).collect()
    assert result.data.status.available is False
    assert result.error


def test_collect_malformed_entry_returns_unavailable() -> None:
    result = _source(api=FakeApi(answer={"Images": [{"no_id": 1}]})).collect()
    assert result.data.status.available is False


def test_collect_empty_exception_message_names_the_type() -> None:
    result = _source(api=FakeApi(failure=docker.errors.DockerException())).collect()
    assert result.error == "DockerException"


def test_collect_recovers_after_failure() -> None:
    api = FakeApi(failure=docker.errors.DockerException("down"))
    source = _source(api=api)
    assert source.collect().data.status.available is False
    api.failure, api.answer = None, {}
    assert source.collect().data.status.available is True


def test_default_source_reads_a_pool_with_the_df_timeout_never_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timeouts: list[int] = []

    def forbidden(**_: Any) -> None:
        raise AssertionError("docker.from_env follows an unvalidated DOCKER_HOST")

    def fake_pool(*, timeout: int) -> FixedEngines:
        timeouts.append(timeout)
        return FixedEngines(client=FakeClient(api=FakeApi(answer={})))

    monkeypatch.setattr(target=docker, name="from_env", value=forbidden)
    monkeypatch.setattr(target=disk_report, name="local_pool", value=fake_pool)
    source = DockerDiskSource()

    assert source.collect().data.status.available is True
    assert source.collect().data.status.available is True
    assert timeouts == [DF_TIMEOUT_S]


def test_the_report_reads_the_primary_engine_only() -> None:
    primary = FakeClient(api=FakeApi(answer={}))
    other = FakeClient(api=FakeApi(failure=docker.errors.DockerException("not me")))
    provider = FakeProvider(
        engines=(engine_at(path="/a.sock", client=primary), engine_at(path="/b.sock", client=other))
    )

    result = DockerDiskSource(engines=provider).collect()

    assert result.data.status.available is True and result.error is None
    assert primary.api.calls == 1 and other.api.calls == 0


def test_no_reachable_engine_is_unavailable_with_a_reason() -> None:
    result = DockerDiskSource(engines=FakeProvider(engines=())).collect()

    assert result.data.status.available is False
    assert result.error == NO_ENGINE
