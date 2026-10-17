"""Seams of the folder, cache and trash actions: commands, working directories, settings."""

import shutil
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import psutil

from wimm.redaction import redact_text

from .errors import ControlFailed
from .safe_tree import read_mountpoints

OUTPUT_TAIL_CHARS = 200
_Run = Callable[..., "subprocess.CompletedProcess[str]"]


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    output: str


class CommandRunner(Protocol):
    def run(
        self, *, argv: Sequence[str], timeout_s: float, env: Mapping[str, str] | None = None
    ) -> CommandResult:
        """Run a command given as a list; raise `ControlFailed` if it cannot start or times out.

        `env` replaces the inherited environment when given."""
        ...


class CwdSource(Protocol):
    def cwds(self) -> Sequence[Path]:
        """Working directories of the user's processes that can be read."""
        ...


class SubprocessRunner:
    """Real runner: argument list, no shell, no stdin, captured output."""

    def __init__(self, *, run: _Run = subprocess.run) -> None:
        self._run = run

    def run(
        self, *, argv: Sequence[str], timeout_s: float, env: Mapping[str, str] | None = None
    ) -> CommandResult:
        tool = argv[0]
        try:
            done = self._run(
                list(argv),
                stdin=subprocess.DEVNULL,
                env=None if env is None else dict(env),
                capture_output=True,
                text=True,
                errors="replace",
                timeout=timeout_s,
                check=False,
            )
        except FileNotFoundError as error:
            raise ControlFailed(f"{tool} was not found on PATH") from error
        except subprocess.TimeoutExpired as error:
            raise ControlFailed(f"{tool} did not finish within {timeout_s} s") from error
        except OSError as error:
            raise ControlFailed(f"Cannot run {tool}: {error}") from error
        output = redact_text(f"{done.stdout}{done.stderr}".strip())
        return CommandResult(returncode=done.returncode, output=output[-OUTPUT_TAIL_CHARS:])


class PsutilCwds:
    """Working directories of the processes of one user; unreadable ones are left out."""

    def __init__(self, *, owner_uid: int) -> None:
        self._owner_uid = owner_uid

    def cwds(self) -> Sequence[Path]:
        found: list[Path] = []
        for process in psutil.process_iter(["cwd", "uids"]):
            uids = process.info.get("uids")
            cwd = process.info.get("cwd")
            if cwd and uids is not None and uids.real == self._owner_uid:
                found.append(Path(cwd))
        return found


@dataclass(frozen=True, slots=True, kw_only=True)
class DiskFsControl:
    """What the folder actions need from the system.

    `home` is the only place cache and trash are looked up; `roots` and `min_age_days` follow
    the configuration. Everything else is injectable so tests never run a real command.
    """

    home: Path
    roots: tuple[Path, ...]
    min_age_days: int
    runner: CommandRunner
    cwds: CwdSource
    which: Callable[[str], str | None] = shutil.which
    mounts: Callable[[], frozenset[str]] = read_mountpoints
    clock: Callable[[], float] = time.time
