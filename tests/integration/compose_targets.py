"""Compose projects created (and always purged) by the integration tests. Never touches others."""

import json
import shutil
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any
from uuid import uuid4

import docker.errors

from tests.integration.docker_targets import IMAGE, QUICK_STOP_COMMAND, TEST_LABELS
from tests.integration.live_targets import run_argv

PROJECT_LABEL = "com.docker.compose.project"
TEST_LABEL = "wimm.test=1"
VOLUME_NAME = "data"
SERVICES = ("a", "b")


def _compose_document() -> dict[str, Any]:
    services: dict[str, Any] = {
        name: {
            "image": IMAGE,
            "pull_policy": "never",
            "command": QUICK_STOP_COMMAND,
            "labels": TEST_LABELS,
        }
        for name in SERVICES
    }
    services["a"]["volumes"] = [f"{VOLUME_NAME}:/data"]
    return {
        "services": services,
        "volumes": {VOLUME_NAME: {"labels": TEST_LABELS}},
        "networks": {"default": {"labels": TEST_LABELS}},
    }


def new_project_name() -> str:
    """Unique, prefixed so a leftover can never be mistaken for a user's project."""
    return f"wimmtest-{uuid4().hex[:8]}"


def project_resources(*, client: Any, project: str) -> dict[str, list[Any]]:
    """Containers (any state), volumes and networks labelled with the test project."""
    flt = {"label": [f"{PROJECT_LABEL}={project}"]}
    return {
        "containers": client.containers.list(all=True, filters=flt),
        "volumes": client.volumes.list(filters=flt),
        "networks": client.networks.list(filters=flt),
    }


def purge(*, client: Any, project: str) -> None:
    """Remove whatever is labelled `wimm.test=1` or belongs to the test project."""
    for flt in ({"label": [TEST_LABEL]}, {"label": [f"{PROJECT_LABEL}={project}"]}):
        for container in client.containers.list(all=True, filters=flt):
            with suppress(docker.errors.NotFound):
                container.remove(force=True, v=True)
        for network in client.networks.list(filters=flt):
            with suppress(docker.errors.NotFound):
                network.remove()
        for volume in client.volumes.list(filters=flt):
            with suppress(docker.errors.NotFound):
                volume.remove(force=True)


@contextmanager
def compose_project(*, client: Any, directory: Path) -> Iterator[str]:
    """Bring up a two-service project from a compose file, then delete the file.

    The file is gone before the test acts, so every command must work from labels alone.
    """
    project = new_project_name()
    file = directory / "compose.yaml"
    file.write_text(json.dumps(_compose_document()), encoding="utf-8")
    docker_bin = shutil.which("docker")
    assert docker_bin is not None
    try:
        args = [docker_bin, "compose", "-f", str(file), "-p", project, "up", "-d"]
        run_argv(args=args, cwd=directory)
        file.unlink()
        yield project
    finally:
        purge(client=client, project=project)
