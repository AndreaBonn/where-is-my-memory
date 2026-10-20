"""T-6.37c: every way `ollama list` can fail gives no entry and one WARNING, never data."""

import logging

import pytest

from tests.collectors.ollama_models_helpers import (
    CONNECT_ERROR,
    FakeRunner,
    collect,
    home_entry,
    listing,
)
from wimm.collectors.ollama_command import CommandOutput, OllamaCommandError

LOGGER = "wimm.collectors.ollama_models"
HEADER = "NAME                  ID              SIZE      MODIFIED     \n"


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]


def test_unreachable_server_exit_1_gives_no_entry_and_one_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    runner = FakeRunner(output=CommandOutput(returncode=1, stdout="", stderr=CONNECT_ERROR))
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert collect(runner=runner) is None
    (message,) = _warnings(caplog)
    assert "exit code 1" in message
    assert "could not connect" in message


def test_the_logged_output_loses_terminal_escapes_and_control_characters(
    caplog: pytest.LogCaptureFixture,
) -> None:
    noisy = CommandOutput(returncode=1, stdout="", stderr="\x1b[2Kboom\x1b[?25h\x07\r")
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert collect(runner=FakeRunner(output=noisy)) is None
    (message,) = _warnings(caplog)
    assert "boom" in message
    assert "\x1b" not in message
    assert "\x07" not in message


def test_timeout_gives_no_entry_and_one_warning(caplog: pytest.LogCaptureFixture) -> None:
    runner = FakeRunner(error=OllamaCommandError("ollama did not finish within 10 s"))
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert collect(runner=runner) is None
    (message,) = _warnings(caplog)
    assert "did not finish" in message


@pytest.mark.parametrize(
    "stdout",
    [
        "",
        "garbage\n",
        listing().replace("a2af6cc3eb7f", "a2af6cc3eb7"),  # one id of 11 digits
        listing().replace("gemma3:4b", "-rf:x"),
    ],
)
def test_output_the_parser_rejects_gives_no_entry_and_one_warning(
    stdout: str, caplog: pytest.LogCaptureFixture
) -> None:
    runner = FakeRunner(output=CommandOutput(returncode=0, stdout=stdout, stderr=""))
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert collect(runner=runner) is None
    assert len(_warnings(caplog)) == 1
    assert collect(runner=FakeRunner()) is not None  # the intact output is accepted


def test_header_only_gives_no_entry_and_one_warning(caplog: pytest.LogCaptureFixture) -> None:
    runner = FakeRunner(output=CommandOutput(returncode=0, stdout=HEADER, stderr=""))
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert collect(runner=runner) is None
    assert len(_warnings(caplog)) == 1


NAMES = ("qwen3-embedding:8b", "gemma3:4b", "qwen3.5:9b", "qwen2.5vl:7b")


def test_same_names_as_the_home_store_gives_no_entry(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert collect(runner=FakeRunner(), caches=(home_entry(*NAMES),)) is None
    (message,) = _warnings(caplog)
    assert "home" in message


def test_different_or_partial_home_names_keep_the_entry() -> None:
    assert collect(runner=FakeRunner(), caches=(home_entry(*NAMES[:3]),)) is not None
    assert collect(runner=FakeRunner(), caches=(home_entry("other:1b"),)) is not None


def test_an_empty_home_store_does_not_hide_the_entry() -> None:
    assert collect(runner=FakeRunner(), caches=(home_entry(),)) is not None
