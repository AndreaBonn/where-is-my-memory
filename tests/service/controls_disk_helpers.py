from typing import Any

import docker.errors

from wimm.collectors.docker_engines import FixedEngines
from wimm.service.controls import DockerSdkControl

IMAGE_ID = "sha256:" + "a" * 64
CREATED_AT = "2026-10-01T10:00:00Z"


class FakeApi:
    def __init__(
        self,
        *,
        containers: list[dict[str, Any]],
        reclaimed: int = 0,
        failure: Exception | None = None,
    ) -> None:
        self._containers = containers
        self._reclaimed = reclaimed
        self._failure = failure
        self.image_records: list[dict[str, Any]] = []
        self.posts: list[tuple[str, dict[str, str], float]] = []
        self.filters: list[dict[str, Any] | None] = []

    def containers(self, *, all: bool, filters: dict[str, Any] | None = None) -> list[Any]:
        assert all is True
        self.filters.append(filters)
        if filters is None:
            return self._containers
        return [c for c in self._containers if filters["volume"][0] in c.get("Volumes", [])]

    def _url(self, pathfmt: str) -> str:
        return "http://daemon" + pathfmt

    def images(self, *, all: bool) -> list[dict[str, Any]]:
        assert all is True
        return self.image_records

    def _post(self, url: str, *, params: dict[str, str], timeout: float) -> Any:
        if self._failure is not None:
            raise self._failure
        self.posts.append((url, params, timeout))
        return {"SpaceReclaimed": self._reclaimed}

    def _result(self, response: Any, json: bool) -> Any:
        assert json is True
        return response


class FakeImage:
    def __init__(self, *, image_id: str, tags: list[str] | None = None) -> None:
        self.id = image_id
        self.tags = tags or []


class FakeImages:
    def __init__(self) -> None:
        self.known = {IMAGE_ID: FakeImage(image_id=IMAGE_ID)}
        self.removed: list[tuple[str, bool]] = []

    def get(self, name: str) -> FakeImage:
        if name in self.known:
            return self.known[name]
        for image in self.known.values():
            if name in image.tags:
                return image
        raise docker.errors.ImageNotFound("gone")

    def remove(self, image: str, *, noprune: bool) -> Any:
        if image not in self.known and not any(image in k.tags for k in self.known.values()):
            raise docker.errors.ImageNotFound("gone")
        self.removed.append((image, noprune))


class FakeVolume:
    def __init__(self, *, owner: "FakeVolumes", name: str) -> None:
        self._owner = owner
        self._name = name

    @property
    def attrs(self) -> dict[str, Any]:
        return {"CreatedAt": CREATED_AT}

    def remove(self) -> None:
        self._owner.removed.append(self._name)


class FakeVolumes:
    def __init__(self, *, names: set[str]) -> None:
        self.names = names
        self.removed: list[str] = []

    def get(self, volume_id: str) -> FakeVolume:
        if volume_id not in self.names:
            raise docker.errors.NotFound("gone")
        return FakeVolume(owner=self, name=volume_id)


class FakeClient:
    def __init__(
        self,
        *,
        containers: list[dict[str, Any]],
        reclaimed: int = 0,
        failure: Exception | None = None,
    ) -> None:
        self.images = FakeImages()
        self.volumes = FakeVolumes(names={"data", "busy"})
        self.api = FakeApi(containers=containers, reclaimed=reclaimed, failure=failure)

    @property
    def containers(self) -> Any:
        raise AssertionError("not used by the disk operations")


def control(
    *,
    containers: list[dict[str, Any]] | None = None,
    reclaimed: int = 0,
    failure: Exception | None = None,
) -> Any:
    client = FakeClient(containers=containers or [], reclaimed=reclaimed, failure=failure)
    return DockerSdkControl(engines=FixedEngines(client=client)), client
