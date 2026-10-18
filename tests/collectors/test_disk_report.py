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
    """`inspections` maps an image id to its inspect answer, or to the error it raises.

    An id missing from it answers like an engine older than API 1.53: no `Identity`.
    """

    def __init__(
        self,
        *,
        answer: Any = None,
        failure: Exception | None = None,
        inspections: dict[str, Any] | None = None,
        api_version: str = "1.41",
    ) -> None:
        self.answer, self.failure, self.calls = answer, failure, 0
        self.api_version = api_version
        self.inspections = inspections or {}
        self.inspected: list[str] = []

    def df(self) -> Any:
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        return self.answer

    def inspect_image(self, image: str) -> Any:
        self.inspected.append(image)
        found = self.inspections.get(image, {"Id": image})
        if isinstance(found, Exception):
            raise found
        return found


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
    assert result.error and result.error == result.data.status.error
    assert result.data.images == () and result.data.volumes == ()
    assert result.data.build_cache_size == 0


def test_collect_malformed_entry_returns_unavailable() -> None:
    result = _source(api=FakeApi(answer={"Images": [{"no_id": 1}]})).collect()
    assert result.data.status.available is False
    assert result.error and result.error == result.data.status.error
    assert result.data.images == ()


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


class RecordingProvider(FakeProvider):
    def __init__(self, *, engines: tuple[Any, ...]) -> None:
        super().__init__(engines=engines)
        self.discarded: list[Any] = []

    def discard(self, *, engine: Any) -> None:
        self.discarded.append(engine)


def test_a_failed_read_discards_the_engine_and_a_good_read_keeps_it() -> None:
    api = FakeApi(failure=docker.errors.DockerException("down"))
    engine = engine_at(path="/a.sock", client=FakeClient(api=api))
    provider = RecordingProvider(engines=(engine,))
    source = DockerDiskSource(engines=provider)

    assert source.collect().data.status.available is False
    assert provider.discarded == [engine]

    api.failure, api.answer = None, {}
    assert source.collect().data.status.available is True
    assert provider.discarded == [engine]


def test_no_reachable_engine_discards_nothing() -> None:
    provider = RecordingProvider(engines=())

    assert DockerDiskSource(engines=provider).collect().error == NO_ENGINE
    assert provider.discarded == []


PYTHON_SLIM = "sha256:" + "b" * 64
NGINX = "sha256:" + "a" * 64
BUILT_HERE = {"Identity": {"Build": [{"Ref": "x1", "CreatedAt": "2026-10-13T21:58:45Z"}]}}
PULLED = {"Identity": {"Pull": [{"Repository": "docker.io/library/python"}]}}


def _local_flags(
    *, inspections: dict[str, Any], api_version: str = "1.41"
) -> tuple[dict[str, bool], FakeApi]:
    api = FakeApi(
        answer=json.loads(FIXTURE.read_text()), inspections=inspections, api_version=api_version
    )
    result = _source(api=api).collect()
    assert result.error is None
    return {i.id: i.local_build for i in result.data.images}, api


def test_an_image_with_digests_built_here_is_a_local_build() -> None:
    flags, _ = _local_flags(inspections={PYTHON_SLIM: BUILT_HERE})

    assert flags[PYTHON_SLIM] is True


def test_an_image_pulled_from_a_registry_stays_pullable() -> None:
    flags, _ = _local_flags(inspections={PYTHON_SLIM: PULLED})

    assert flags[PYTHON_SLIM] is False


def test_an_image_that_cannot_be_inspected_counts_as_a_local_build() -> None:
    gone = docker.errors.NotFound("no such image")
    flags, _ = _local_flags(inspections={PYTHON_SLIM: gone, NGINX: PULLED})

    assert flags[PYTHON_SLIM] is True
    assert flags[NGINX] is False


def test_only_images_with_digests_are_inspected() -> None:
    _, api = _local_flags(inspections={})

    assert sorted(api.inspected) == [NGINX, PYTHON_SLIM]


def test_on_an_engine_with_identity_an_answer_without_it_is_a_local_build() -> None:
    flags, _ = _local_flags(inspections={NGINX: PULLED}, api_version="1.56")

    assert flags[PYTHON_SLIM] is True
    assert flags[NGINX] is False


def test_an_unexpected_inspect_error_keeps_the_report_available() -> None:
    flags, _ = _local_flags(inspections={PYTHON_SLIM: ValueError("bad json"), NGINX: PULLED})

    assert flags[PYTHON_SLIM] is True
    assert flags[NGINX] is False


def test_past_the_inspect_budget_the_remaining_images_count_as_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticks = iter([0.0, 0.0, disk_report.INSPECT_BUDGET_S + 1])
    monkeypatch.setattr("wimm.collectors.disk_report.time.monotonic", lambda: next(ticks, 999.0))

    flags, api = _local_flags(inspections={NGINX: PULLED, PYTHON_SLIM: PULLED})

    assert len(api.inspected) == 1
    assert sorted(flags[i] for i in (NGINX, PYTHON_SLIM)) == [False, True]
