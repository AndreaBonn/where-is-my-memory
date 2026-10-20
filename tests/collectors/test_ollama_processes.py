"""T-6.37c: the `ollama serve` processes and the environ only of the user's own (fake psutil)."""

import psutil

from tests.collectors.ollama_models_helpers import CURRENT_UID, SERVICE_UID, FakeProcess, FakeReader
from wimm.collectors.ollama_processes import collect_serve_processes
from wimm.core.ollama_served import ServeProcess


def _collect(*processes: FakeProcess) -> tuple[ServeProcess, ...]:
    return collect_serve_processes(reader=FakeReader(*processes), current_uid=CURRENT_UID)


def test_system_server_is_found_with_its_uid_and_environ_is_not_read() -> None:
    server = FakeProcess(uid=SERVICE_UID)
    assert _collect(server) == (ServeProcess(uid=SERVICE_UID, environ=None),)
    assert server.environ_calls == 0


def test_own_server_environ_is_read() -> None:
    server = FakeProcess(uid=CURRENT_UID, environ_value={"OLLAMA_MODELS": "/data/m"})
    assert _collect(server) == (
        ServeProcess(uid=CURRENT_UID, environ={"OLLAMA_MODELS": "/data/m"}),
    )
    assert server.environ_calls == 1


def test_own_server_with_unreadable_environ_has_none() -> None:
    server = FakeProcess(uid=CURRENT_UID, environ_error=psutil.AccessDenied(pid=1))
    assert _collect(server) == (ServeProcess(uid=CURRENT_UID, environ=None),)


def test_only_ollama_serve_counts() -> None:
    others = [
        FakeProcess(uid=1, cmdline=["/usr/local/bin/ollama", "run", "gemma3:4b"]),
        FakeProcess(uid=2, cmdline=["/usr/bin/python3", "ollama", "serve"]),
        FakeProcess(uid=3, cmdline=["/home/u/.ollama/serve"]),
        FakeProcess(uid=4, cmdline=[]),
        FakeProcess(uid=5, cmdline=None),
    ]
    assert _collect(*others) == ()
    assert _collect(*others, FakeProcess(uid=6, cmdline=["ollama", "serve"])) == (
        ServeProcess(uid=6, environ=None),
    )


def test_a_process_that_vanished_is_skipped() -> None:
    class Vanishing(FakeProcess):
        @property
        def info(self) -> dict[str, object]:
            raise psutil.NoSuchProcess(pid=1)

    assert _collect(Vanishing(uid=SERVICE_UID), FakeProcess(uid=SERVICE_UID)) == (
        ServeProcess(uid=SERVICE_UID, environ=None),
    )
