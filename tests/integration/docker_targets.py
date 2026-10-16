"""Containers created (and always removed) by the Docker integration tests."""

from collections.abc import Iterator
from contextlib import contextmanager, suppress
from typing import Any

import docker
import docker.errors

IMAGE = "alpine:3"
TEST_LABELS = {"wimm.test": "1"}
# PID 1 ignores SIGTERM unless it traps it; trapping keeps `stop` well under its timeout.
QUICK_STOP_COMMAND = ["sh", "-c", "trap 'exit 0' TERM; while true; do sleep 1; done"]


def connect() -> Any:
    """Return a Docker client, or raise `RuntimeError` with the reason it cannot be used."""
    try:
        client: Any = docker.from_env()
        client.ping()
        client.images.get(IMAGE)
    except docker.errors.ImageNotFound as error:
        raise RuntimeError(f"image {IMAGE} not present locally; tests never pull") from error
    except (docker.errors.DockerException, OSError) as error:
        raise RuntimeError(f"Docker daemon not reachable: {error}") from error
    return client


@contextmanager
def started_container(*, client: Any) -> Iterator[Any]:
    """Run a labelled alpine container; force-remove it on exit, whatever happened."""
    container = client.containers.run(IMAGE, QUICK_STOP_COMMAND, detach=True, labels=TEST_LABELS)
    try:
        yield container
    finally:
        with suppress(docker.errors.NotFound):
            container.remove(force=True)


def exists(*, client: Any, container_id: str) -> bool:
    try:
        client.containers.get(container_id)
    except docker.errors.NotFound:
        return False
    return True
