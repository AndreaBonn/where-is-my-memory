"""The `ollama serve` processes, with their real uid (T-6.37c, design note section 3).

`/proc/<pid>/environ` of another user's process is denied, so it is read only for the
current user's own server; for the others the answer is "unknown" (None), never a guess.
"""

import logging
from collections.abc import Iterable, Mapping
from pathlib import PurePosixPath
from typing import Any, Protocol

import psutil

from wimm.core.constants import OLLAMA_NAME
from wimm.core.ollama_serve import OLLAMA_SERVE_ARGUMENT
from wimm.core.ollama_served import ServeProcess

LOGGER = logging.getLogger(__name__)
SERVE_ATTRS = ["cmdline", "uids"]


class ServeCandidate(Protocol):
    """What of a psutil process the collector uses; a fake needs no real process."""

    @property
    def info(self) -> dict[str, Any]: ...

    def environ(self) -> Mapping[str, str]: ...


class ServeReader(Protocol):
    def process_iter(self, attrs: list[str]) -> Iterable[ServeCandidate]: ...


def _is_serve(*, cmdline: list[str] | None) -> bool:
    """The command line is `<...>/ollama serve`: the binary, then `serve` as first argument."""
    if not cmdline or len(cmdline) < 2:
        return False
    return PurePosixPath(cmdline[0]).name == OLLAMA_NAME and cmdline[1] == OLLAMA_SERVE_ARGUMENT


def _environ_of(*, process: ServeCandidate) -> dict[str, str] | None:
    try:
        return dict(process.environ())
    except (psutil.Error, OSError):
        return None


def _serve_process(*, process: ServeCandidate, current_uid: int) -> ServeProcess | None:
    try:
        info = process.info
        if not _is_serve(cmdline=info["cmdline"]):
            return None
        uid = int(info["uids"].real)
    except (psutil.Error, KeyError, AttributeError):
        return None
    environ = _environ_of(process=process) if uid == current_uid else None
    return ServeProcess(uid=uid, environ=environ)


def collect_serve_processes(*, reader: ServeReader, current_uid: int) -> tuple[ServeProcess, ...]:
    """Every `ollama serve` visible to the current user; unreadable processes are skipped."""
    found = (
        _serve_process(process=process, current_uid=current_uid)
        for process in reader.process_iter(SERVE_ATTRS)
    )
    return tuple(item for item in found if item is not None)
