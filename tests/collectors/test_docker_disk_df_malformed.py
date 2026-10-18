import json
import logging
from pathlib import Path
from typing import Any

import pytest

from wimm.collectors import CollectorResult
from wimm.collectors.disk_report import DockerDiskSource
from wimm.collectors.docker_engines import FixedEngines
from wimm.model.disk import DockerDisk

FIXTURE = Path(__file__).parent.parent / "fixtures" / "docker_df.json"
ITALIAN_MESSAGE = "Docker ha risposto in un formato inatteso"
ENGLISH_MESSAGE = "Docker answered in an unexpected format"


class _Api:
    def __init__(self, *, answer: Any) -> None:
        self.answer = answer
        self.api_version = "1.41"

    def df(self) -> Any:
        return self.answer

    def inspect_image(self, image: str) -> Any:
        return {"Id": image}


class _Client:
    def __init__(self, *, answer: Any) -> None:
        self.api = _Api(answer=answer)


def _collect(*, answer: Any) -> CollectorResult[DockerDisk]:
    return DockerDiskSource(engines=FixedEngines(client=_Client(answer=answer))).collect()


def _missing_image_id() -> dict[str, Any]:
    raw: dict[str, Any] = json.loads(FIXTURE.read_text())
    del raw["Images"][0]["Id"]
    return raw


def _list_instead_of_object() -> dict[str, Any]:
    raw: dict[str, Any] = json.loads(FIXTURE.read_text())
    raw["Images"][0] = []
    return raw


MALFORMED = [
    pytest.param(_missing_image_id, "'Id'", id="missing-key"),
    pytest.param(_list_instead_of_object, "list indices", id="list-for-object"),
]


@pytest.mark.parametrize(("build", "raw_text"), MALFORMED)
def test_malformed_df_shows_a_plain_message_not_the_exception_text(
    build: Any, raw_text: str
) -> None:
    result = _collect(answer=build())

    assert result.error == ITALIAN_MESSAGE
    assert result.data.status.available is False
    assert result.data.status.error == ITALIAN_MESSAGE
    assert raw_text not in (result.error or "")


@pytest.mark.usefixtures("english")
@pytest.mark.parametrize(("build", "raw_text"), MALFORMED)
def test_malformed_df_message_is_translated(build: Any, raw_text: str) -> None:
    result = _collect(answer=build())

    assert result.error == ENGLISH_MESSAGE
    assert raw_text not in (result.error or "")


@pytest.mark.parametrize(("build", "raw_text"), MALFORMED)
def test_malformed_df_detail_goes_to_the_log_at_warning(
    build: Any, raw_text: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG, logger="wimm.collectors.disk_report"):
        _collect(answer=build())

    records = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(records) == 1
    assert records[0].exc_info is not None
    assert raw_text in caplog.text


def test_wellformed_df_logs_nothing_and_has_no_error(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG, logger="wimm.collectors.disk_report"):
        result = _collect(answer=json.loads(FIXTURE.read_text()))

    assert result.error is None
    assert caplog.records == []
