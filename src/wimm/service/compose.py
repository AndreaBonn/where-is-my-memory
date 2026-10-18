"""Compose project control on the `docker compose` CLI (SPECIFICHE 7.3, 8.4)."""

import os
import re
import shutil
import subprocess
from collections.abc import Callable

import docker.errors

from wimm.collectors.docker_engines import Engine, EngineProvider
from wimm.core.constants import COMPOSE_TIMEOUT_S
from wimm.core.docker_endpoint import UNIX_PREFIX
from wimm.core.docker_notices import notices_text
from wimm.core.grouping_keys import COMPOSE_PROJECT_LABEL
from wimm.redaction import redact_text

from .errors import ControlFailed, DockerUnavailable, InvalidRequest

# Compose itself only produces lowercase letters, digits, `-` and `_`, starting with an
# alphanumeric: anything else cannot be an observed project, and a leading `-` would be a flag.
PROJECT_NAME = re.compile(r"[a-z0-9][a-z0-9_-]*")
# Probed in T-3.6 from a directory that is not the project's: no compose file is found
# there, so `down` works from the labels only (docs/DEVIATIONS.md).
NEUTRAL_CWD = "/"
STDERR_TAIL_CHARS = 500
# The engine that revalidated the project is reached on a validated unix socket; the CLI would
# also follow DOCKER_HOST (even tcp://), a selected context and the user's COMPOSE_* variables,
# so it could act on another daemon or another file. "--host unix://<socket>" plus this cleanup
# pins it to that engine.
IGNORED_ENV_PREFIX = "COMPOSE_"
IGNORED_ENV = frozenset({"DOCKER_CONTEXT", "DOCKER_HOST"})


def cli_environment(*, environ: dict[str, str]) -> dict[str, str]:
    """The user's environment without what could point the CLI elsewhere."""
    return {
        name: value
        for name, value in environ.items()
        if name not in IGNORED_ENV and not name.startswith(IGNORED_ENV_PREFIX)
    }


_Runner = Callable[..., "subprocess.CompletedProcess[str]"]


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
    The project's containers are the union over the local engines; `down` is pinned to the
    one engine that hosts them and refuses a project spread over several.
    """

    def __init__(
        self,
        *,
        engines: EngineProvider,
        docker_bin: str,
        runner: _Runner = subprocess.run,
    ) -> None:
        self._engines = engines
        self._docker_bin = docker_bin
        self._runner = runner

    def container_ids(self, *, project: str) -> frozenset[str]:
        label = f"{COMPOSE_PROJECT_LABEL}={_checked(project=project)}"
        found = (ids for _, ids in self._listing(project=project, label=label))
        return frozenset().union(*found)

    def down(self, *, project: str, volumes: bool) -> None:
        label = f"{COMPOSE_PROJECT_LABEL}={_checked(project=project)}"
        listing = self._listing(project=project, label=label)
        hosts = [engine for engine, ids in listing if ids]
        if len(hosts) > 1:
            paths = ", ".join(engine.identity.path for engine in hosts)
            raise ControlFailed(f"Compose project {project} runs on several engines ({paths})")
        engine = (hosts or [engine for engine, _ in listing])[0]
        argv = [self._docker_bin, "--host", UNIX_PREFIX + engine.identity.path]
        argv += ["compose", "-p", project, "down"]
        if volumes:
            argv.append("-v")
        self._run(argv=argv, project=project)

    def _listing(self, *, project: str, label: str) -> list[tuple[Engine, frozenset[str]]]:
        view = self._engines.refresh()
        if not view.engines:
            raise DockerUnavailable(notices_text(notices=view.notices) or "no container engine")
        try:
            return [
                (
                    engine,
                    frozenset(
                        c.id
                        for c in engine.client.containers.list(all=True, filters={"label": label})
                    ),
                )
                for engine in view.engines
            ]
        except (docker.errors.DockerException, OSError) as error:
            raise ControlFailed(f"Cannot list containers of project {project}: {error}") from error

    def _run(self, *, argv: list[str], project: str) -> None:
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
