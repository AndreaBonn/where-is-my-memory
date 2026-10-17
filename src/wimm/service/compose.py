"""Compose project control on the `docker compose` CLI (SPECIFICHE 7.3, 8.4)."""

import os
import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from typing import Any, Protocol

import docker
import docker.errors

from wimm.core.constants import COMPOSE_TIMEOUT_S
from wimm.core.grouping_keys import COMPOSE_PROJECT_LABEL
from wimm.redaction import redact_text

from .errors import ControlFailed, InvalidRequest

# Compose itself only produces lowercase letters, digits, `-` and `_`, starting with an
# alphanumeric: anything else cannot be an observed project, and a leading `-` would be a flag.
PROJECT_NAME = re.compile(r"[a-z0-9][a-z0-9_-]*")
# Probed in T-3.6 from a directory that is not the project's: no compose file is found
# there, so `down` works from the labels only (docs/DEVIATIONS.md).
NEUTRAL_CWD = "/"
STDERR_TAIL_CHARS = 500
# The SDK that revalidated the project reads DOCKER_HOST or the default socket; the CLI would
# also follow a selected context and the user's COMPOSE_* variables, so it could act on
# another daemon or another file. "--context default" plus this cleanup pins it to the SDK's.
DAEMON_ARGS = ("--context", "default")
IGNORED_ENV_PREFIX = "COMPOSE_"
IGNORED_ENV = frozenset({"DOCKER_CONTEXT"})


def cli_environment(*, environ: dict[str, str]) -> dict[str, str]:
    """The user's environment without what could point the CLI elsewhere."""
    return {
        name: value
        for name, value in environ.items()
        if name not in IGNORED_ENV and not name.startswith(IGNORED_ENV_PREFIX)
    }


_Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class _ContainerLike(Protocol):
    @property
    def id(self) -> str: ...


class _ContainerList(Protocol):
    def list(self, *, all: bool, filters: dict[str, str]) -> Sequence[_ContainerLike]: ...


class ComposeClientLike(Protocol):
    @property
    def containers(self) -> _ContainerList: ...


def resolve_docker_binary(*, which: Callable[[str], str | None] = shutil.which) -> str:
    """Return the absolute path of the `docker` CLI, or raise a clear `ControlFailed`."""
    found = which("docker")
    if found is None:
        raise ControlFailed("The docker command was not found in PATH: compose is unavailable")
    return found


def _checked(*, project: str) -> str:
    if PROJECT_NAME.fullmatch(project) is None:
        raise InvalidRequest(f"{project!r} is not a compose project name")
    return project


class DockerComposeControl:
    """Run `docker compose -p <project> down` and list a project's containers by label.

    The argv is a list and the project name is checked against the compose name grammar
    before it is used; it comes from the plan, itself built from the observed snapshot.
    """

    def __init__(
        self,
        *,
        client: ComposeClientLike,
        docker_bin: str,
        runner: _Runner = subprocess.run,
    ) -> None:
        self._client = client
        self._docker_bin = docker_bin
        self._runner = runner

    @classmethod
    def from_env(cls) -> "DockerComposeControl":
        docker_bin = resolve_docker_binary()
        client: Any = docker.from_env()
        return cls(client=client, docker_bin=docker_bin)

    def container_ids(self, *, project: str) -> frozenset[str]:
        label = f"{COMPOSE_PROJECT_LABEL}={_checked(project=project)}"
        try:
            found = self._client.containers.list(all=True, filters={"label": label})
        except (docker.errors.DockerException, OSError) as error:
            raise ControlFailed(f"Cannot list containers of project {project}: {error}") from error
        return frozenset(container.id for container in found)

    def down(self, *, project: str, volumes: bool) -> None:
        argv = [self._docker_bin, *DAEMON_ARGS, "compose", "-p", _checked(project=project), "down"]
        if volumes:
            argv.append("-v")
        try:
            done = self._runner(
                argv,
                check=False,
                timeout=COMPOSE_TIMEOUT_S,
                capture_output=True,
                text=True,
                errors="replace",
                cwd=NEUTRAL_CWD,
                env=cli_environment(environ=dict(os.environ)),
            )
        except subprocess.TimeoutExpired as error:
            raise ControlFailed(
                f"compose down of {project} exceeded {COMPOSE_TIMEOUT_S} s"
            ) from error
        except OSError as error:
            raise ControlFailed(f"Cannot run docker compose: {error}") from error
        if done.returncode != 0:
            tail = redact_text(text=done.stderr.strip()[-STDERR_TAIL_CHARS:])
            raise ControlFailed(f"compose down of {project} failed ({done.returncode}): {tail}")
