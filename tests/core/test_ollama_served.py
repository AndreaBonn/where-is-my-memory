"""T-6.37b: which ollama store `ollama list` and `ollama rm` reach (design note section 3)."""

from collections.abc import Mapping

import pytest

from wimm.core.ollama_served import ServedFacts, ServedStore, ServeProcess, served_store

ME = 1000
OTHER = 997
HOME_STORE = "/home/u/.ollama/models"
OTHER_STORE = "/data/ollama"


def _real(path: str) -> str:
    return {"/home/u/link": HOME_STORE}.get(path, path)


def _facts(
    *processes: ServeProcess, host: str | None = None, home_store: str = HOME_STORE
) -> ServedFacts:
    return ServedFacts(
        processes=processes,
        current_uid=ME,
        ollama_host=host,
        home_store=home_store,
        default_models=HOME_STORE,
    )


def _mine(environ: Mapping[str, str] | None = None) -> ServeProcess:
    return ServeProcess(uid=ME, environ={} if environ is None else environ)


def _system() -> ServeProcess:
    return ServeProcess(uid=OTHER, environ=None)


def _classify(facts: ServedFacts) -> ServedStore:
    return served_store(facts=facts, realpath=_real)


def test_s0_no_server_is_no_store() -> None:
    assert _classify(_facts()) is ServedStore.NONE


def test_s1_user_server_with_the_default_store_serves_the_home() -> None:
    assert _classify(_facts(_mine())) is ServedStore.USER_HOME


def test_s1_user_server_pointed_at_the_home_store_by_variable_serves_the_home() -> None:
    assert _classify(_facts(_mine({"OLLAMA_MODELS": HOME_STORE}))) is ServedStore.USER_HOME


def test_s1_the_variable_is_compared_by_real_path() -> None:
    facts = _facts(_mine({"OLLAMA_MODELS": "/home/u/link"}))

    assert _classify(facts) is ServedStore.USER_HOME


def test_s1_prime_user_server_on_another_store() -> None:
    facts = _facts(_mine({"OLLAMA_MODELS": OTHER_STORE}))

    assert _classify(facts) is ServedStore.USER_OTHER


def test_s1_prime_when_the_home_entry_is_not_the_default_store() -> None:
    assert _classify(_facts(_mine(), home_store=OTHER_STORE)) is ServedStore.USER_OTHER


def test_s1_prime_when_the_environment_cannot_be_read() -> None:
    assert _classify(_facts(ServeProcess(uid=ME, environ=None))) is ServedStore.USER_OTHER


def test_an_empty_variable_counts_as_unset() -> None:
    assert _classify(_facts(_mine({"OLLAMA_MODELS": ""}))) is ServedStore.USER_HOME


def test_s2_one_server_of_another_user_is_the_system_store() -> None:
    assert _classify(_facts(_system())) is ServedStore.SYSTEM


def test_s2_does_not_need_the_environment_of_the_system_server() -> None:
    other = ServeProcess(uid=OTHER, environ={"OLLAMA_MODELS": HOME_STORE})

    assert _classify(_facts(other)) is ServedStore.SYSTEM


@pytest.mark.parametrize(
    "processes",
    [(_mine(), _system()), (_system(), _system()), (_mine(), _mine())],
)
def test_s3_two_servers_are_ambiguous(processes: tuple[ServeProcess, ...]) -> None:
    assert _classify(_facts(*processes)) is ServedStore.AMBIGUOUS


@pytest.mark.parametrize(
    "host",
    ["10.0.0.5:11434", "gpu.example.com", "https://ollama.example.com:443", "[2001:db8::1]:11434"],
)
def test_s3_a_remote_host_is_ambiguous_whatever_runs_here(host: str) -> None:
    assert _classify(_facts(_system(), host=host)) is ServedStore.AMBIGUOUS
    assert _classify(_facts(host=host)) is ServedStore.AMBIGUOUS


@pytest.mark.parametrize(
    "host",
    [
        None,
        "",
        "127.0.0.1",
        "127.0.0.1:11434",
        "localhost:11434",
        "http://localhost:11434",
        "[::1]:11434",
        "0.0.0.0:11434",
        ":11434",
    ],
)
def test_a_local_host_does_not_change_the_classification(host: str | None) -> None:
    assert _classify(_facts(_system(), host=host)) is ServedStore.SYSTEM
    assert _classify(_facts(host=host)) is ServedStore.NONE
