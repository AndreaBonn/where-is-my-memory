"""T-6.37c: the system ollama entry, only in situation S2 (design note sections 1 and 3)."""

import logging

import pytest

from tests.collectors.ollama_models_helpers import (
    CURRENT_UID,
    SERVICE_UID,
    TOOL,
    FakeProcess,
    FakeReader,
    FakeRunner,
    collect,
    scan,
)
from wimm.core.ollama_served import ServedStore
from wimm.model import CacheItemKind, CacheKind, CacheRest

NAMES = {"qwen3-embedding:8b", "gemma3:4b", "qwen3.5:9b", "qwen2.5vl:7b"}
LOGGER = "wimm.collectors.ollama_models"


def test_system_server_gives_one_entry_with_the_listed_models() -> None:
    entry = collect(runner=FakeRunner())
    assert entry is not None
    assert (entry.kind, entry.path, entry.st_ino, entry.st_dev) == (
        CacheKind.OLLAMA_SYSTEM,
        "ollama list",
        0,
        0,
    )
    assert entry.rest == CacheRest()
    assert {item.id for item in entry.items} == NAMES
    assert entry.size == 4_700_000_000 + 3_300_000_000 + 6_600_000_000 + 6_000_000_000
    assert entry.size == sum(item.size for item in entry.items)


def test_each_item_is_built_from_its_row() -> None:
    entry = collect(runner=FakeRunner())
    assert entry is not None
    gemma = next(item for item in entry.items if item.id == "gemma3:4b")
    assert (gemma.title, gemma.path, gemma.model_id) == (
        "gemma3:4b",
        "ollama:gemma3:4b",
        "a2af6cc3eb7f",
    )
    assert (gemma.size, gemma.st_ino, gemma.st_dev, gemma.kind) == (
        3_300_000_000,
        0,
        0,
        CacheItemKind.OLLAMA_MODEL,
    )


def test_list_runs_by_absolute_path_with_the_timeout_and_a_minimal_environment() -> None:
    runner = FakeRunner()
    wanted = {
        "PATH": "/usr/bin",
        "LANG": "it_IT.UTF-8",
        "HOME": "/home/u",
        "OLLAMA_HOST": "127.0.0.1:11434",
    }
    environ = {**wanted, "AWS_SECRET_ACCESS_KEY": "do-not-pass"}
    assert collect(runner=runner, environ=environ) is not None
    (call,) = runner.calls
    assert call["argv"] == [TOOL, "list"]
    assert call["timeout_s"] == 10
    assert call["env"] == wanted


def test_environment_holds_only_what_is_set() -> None:
    runner = FakeRunner()
    assert collect(runner=runner, environ={"PATH": "/usr/bin", "OTHER": "x"}) is not None
    assert runner.calls[0]["env"] == {"PATH": "/usr/bin"}


def test_tool_absent_gives_no_entry_and_runs_nothing(caplog: pytest.LogCaptureFixture) -> None:
    runner = FakeRunner()
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert collect(runner=runner, tool=None) is None
    assert runner.calls == []
    assert "not found" in caplog.text
    assert collect(runner=FakeRunner()) is not None  # same facts with the tool: an entry


def test_a_relative_tool_path_is_refused() -> None:
    runner = FakeRunner()
    assert collect(runner=runner, tool="bin/ollama") is None
    assert runner.calls == []


@pytest.mark.parametrize(
    ("processes", "environ", "situation"),
    [
        ((), {}, "none"),
        ((FakeProcess(uid=CURRENT_UID),), {}, "user_home"),
        ((FakeProcess(uid=CURRENT_UID, environ_error=OSError()),), {}, "user_other"),
        ((FakeProcess(uid=SERVICE_UID), FakeProcess(uid=SERVICE_UID)), {}, "ambiguous"),
        ((FakeProcess(uid=SERVICE_UID),), {"OLLAMA_HOST": "10.0.0.5:11434"}, "ambiguous"),
    ],
)
def test_any_situation_other_than_system_gives_no_entry_and_no_list(
    processes: tuple[FakeProcess, ...],
    environ: dict[str, str],
    situation: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    runner = FakeRunner()
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        entry = collect(runner=runner, reader=FakeReader(*processes), environ=environ)
    assert entry is None
    assert runner.calls == []
    assert situation in caplog.text


def test_the_scan_carries_the_situation_with_the_entry_in_s2() -> None:
    result = scan(runner=FakeRunner())
    assert result.entry is not None
    assert result.situation is ServedStore.SYSTEM


@pytest.mark.parametrize(
    ("processes", "environ", "situation"),
    [
        ((), {}, ServedStore.NONE),
        ((FakeProcess(uid=CURRENT_UID),), {}, ServedStore.USER_HOME),
        ((FakeProcess(uid=CURRENT_UID, environ_error=OSError()),), {}, ServedStore.USER_OTHER),
        ((FakeProcess(uid=SERVICE_UID), FakeProcess(uid=SERVICE_UID)), {}, ServedStore.AMBIGUOUS),
    ],
)
def test_the_scan_carries_the_situation_when_there_is_no_entry(
    processes: tuple[FakeProcess, ...], environ: dict[str, str], situation: ServedStore
) -> None:
    result = scan(runner=FakeRunner(), reader=FakeReader(*processes), environ=environ)
    assert result.entry is None
    assert result.situation is situation


def test_the_situation_is_known_even_when_the_tool_is_missing() -> None:
    result = scan(runner=FakeRunner(), tool=None, reader=FakeReader(FakeProcess(uid=CURRENT_UID)))
    assert result.entry is None
    assert result.situation is ServedStore.USER_HOME
