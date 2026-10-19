"""A container removed while the engine is being listed hides nothing else."""

from collections.abc import Sequence
from pathlib import Path
from typing import cast

import docker.errors

from tests.collectors.test_docker_source import FakeContainer
from wimm.collectors.docker_source import ContainerReader, DockerSource


class VanishingReader:
    """docker-py's list(): it inspects each listed id and one is gone by then.

    Without ``ignore_removed`` the real client raises NotFound for that id, as measured on
    2026-10-19 when a container was removed during the read.
    """

    def __init__(self, kept: FakeContainer) -> None:
        self.kept = kept
        self.containers = self

    def list(self, *, all: bool, ignore_removed: bool = False) -> Sequence[ContainerReader]:
        assert all is True
        if not ignore_removed:
            raise docker.errors.NotFound("No such container: gone")
        return [cast(ContainerReader, self.kept)]


def test_a_container_removed_during_the_listing_leaves_the_others_visible(
    tmp_path: Path,
) -> None:
    source = DockerSource(reader=VanishingReader(kept=FakeContainer()), roots=(tmp_path, tmp_path))

    sample = source.collect().data

    assert sample.status.available is True
    assert [item.id for item in sample.containers] == ["abc"]
