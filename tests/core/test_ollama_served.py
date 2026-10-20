"""T-6.37b: which ollama store `ollama list` and `ollama rm` reach (design note section 3)."""

from collections.abc import Mapping

import pytest

from wimm.core.ollama_served import ServedFacts, ServedStore, ServeProcess, served_store

ME = 1000
OTHER = 997
HOME_STORE = "/home/u/.ollama/models"
OTHER_STORE = "/data/ollama"


def _real(path: str) -> str:
    # "models" is what a relative OLLAMA_MODELS would resolve to from wimm's own cwd.
    return {"/home/u/link": HOME_STORE, "models": HOME_STORE}.get(path, path)


def _facts(
    *processes: ServeProcess,
    host: str | None = None,
    home_store: str = HOME_STORE,
    unreadable: int = 0,
) -> ServedFacts:
    return ServedFacts(
        processes=processes,
        current_uid=ME,
        ollama_host=host,
        home_store=home_store,
        default_models=HOME_STORE,
        unreadable_ollama=unreadable,
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


@pytest.mark.parametrize(
    "host", ["me:secret@127.0.0.1:11434", "@localhost", "http://u@[::1]:11434"]
)
def test_a_host_with_userinfo_is_not_local(host: str) -> None:
    assert _classify(_facts(_system(), host=host)) is ServedStore.AMBIGUOUS
    assert _classify(_facts(host=host)) is ServedStore.AMBIGUOUS


@pytest.mark.parametrize("host", [None, "localhost", "127.0.0.1:11434", "http://[::1]"])
def test_s2_is_allowed_on_the_default_port(host: str | None) -> None:
    assert _classify(_facts(_system(), host=host)) is ServedStore.SYSTEM


@pytest.mark.parametrize("host", ["127.0.0.1:8080", "localhost:11435", ":1", "[::1]:99999"])
def test_s2_on_another_port_is_ambiguous(host: str) -> None:
    assert _classify(_facts(_system(), host=host)) is ServedStore.AMBIGUOUS


def test_a_port_that_is_not_a_number_is_ambiguous() -> None:
    assert _classify(_facts(_system(), host="localhost:abc")) is ServedStore.AMBIGUOUS


def test_s1_the_server_on_the_same_default_port_serves_the_home() -> None:
    environ = {"OLLAMA_HOST": "localhost"}

    assert _classify(_facts(_mine(environ))) is ServedStore.USER_HOME


def test_s1_the_server_on_another_port_than_the_client_is_ambiguous() -> None:
    assert _classify(_facts(_mine({"OLLAMA_HOST": "127.0.0.1:11435"}))) is ServedStore.AMBIGUOUS


def test_s1_the_client_on_another_port_than_the_default_server_is_ambiguous() -> None:
    assert _classify(_facts(_mine(), host="127.0.0.1:11435")) is ServedStore.AMBIGUOUS


def test_s1_the_same_non_default_port_on_both_sides_serves_the_home() -> None:
    facts = _facts(_mine({"OLLAMA_HOST": "0.0.0.0:11435"}), host="localhost:11435")

    assert _classify(facts) is ServedStore.USER_HOME


def test_unreadable_ollama_processes_make_the_situation_ambiguous() -> None:
    assert _classify(_facts(unreadable=1)) is ServedStore.AMBIGUOUS
    assert _classify(_facts(_system(), unreadable=2)) is ServedStore.AMBIGUOUS
    assert _classify(_facts(_mine(), unreadable=1)) is ServedStore.AMBIGUOUS
    assert _classify(_facts(_mine(), unreadable=0)) is ServedStore.USER_HOME


def test_a_relative_models_folder_is_never_resolved_against_the_cwd() -> None:
    assert _classify(_facts(_mine({"OLLAMA_MODELS": "models"}))) is ServedStore.USER_OTHER
    assert _classify(_facts(_mine({"OLLAMA_MODELS": HOME_STORE}))) is ServedStore.USER_HOME


def test_the_default_store_is_below_the_home_of_the_server() -> None:
    other_home = "/srv/ollama"
    served = _mine({"HOME": other_home})

    assert _classify(_facts(served)) is ServedStore.USER_OTHER
    on_it = _facts(served, home_store=f"{other_home}/.ollama/models")
    assert _classify(on_it) is ServedStore.USER_HOME
    assert _classify(_facts(_mine({"HOME": "/home/u"}))) is ServedStore.USER_HOME
