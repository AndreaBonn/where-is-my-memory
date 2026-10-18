"""Docker SDK operations behind the disk actions (SPECIFICHE 8.2, 8.4): images, volumes, cache."""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from enum import Enum
from typing import Any, Protocol

import docker.errors
import requests.exceptions

from wimm.core.constants import BUILD_PRUNE_TIMEOUT_S

from .control_protocols import LiveImage, LiveVolume
from .errors import ControlFailed, TargetGone

# Engine API `POST /build/prune`. Without `all` the daemon keeps records that
# `docker system df` counts as RECLAIMABLE, so the freed space would not match the estimate.
BUILD_PRUNE_PATH = "/build/prune"
BUILD_PRUNE_PARAMS = {"all": "true"}
SPACE_RECLAIMED_KEY = "SpaceReclaimed"
PRUNE_TIMEOUT_MESSAGE = (
    f"Build cache prune timed out after {BUILD_PRUNE_TIMEOUT_S} s: "
    "the daemon may still be freeing space, the result is unknown"
)


class OnMissing(Enum):
    """What a 404 from the daemon means for the call."""

    NONE = "none"  # an inspection: the target is simply not there
    GONE = "gone"  # a removal: the target vanished, `TargetGone`
    FAIL = "fail"  # an endpoint: a 404 is a real failure


@contextmanager
def _sdk_errors(*, action: str, noun: str, on_missing: OnMissing) -> Iterator[None]:
    """Translate SDK failures: a 404 per `on_missing`, anything else is `ControlFailed`."""
    try:
        yield
    except docker.errors.NotFound as error:
        if on_missing is OnMissing.NONE:
            return
        if on_missing is OnMissing.GONE:
            raise TargetGone(f"The {noun} no longer exists") from error
        raise ControlFailed(f"Cannot {action} {noun}: {error}") from error
    except (docker.errors.DockerException, OSError) as error:
        raise ControlFailed(f"Cannot {action} {noun}: {error}") from error


class _ImageLike(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def tags(self) -> list[str]: ...


class _ImageCollection(Protocol):
    def get(self, name: str) -> _ImageLike: ...

    def remove(self, image: str, *, noprune: bool) -> Any: ...


class _VolumeLike(Protocol):
    @property
    def attrs(self) -> dict[str, Any]: ...

    def remove(self) -> None: ...


class _VolumeCollection(Protocol):
    def get(self, volume_id: str) -> _VolumeLike: ...


class _LowLevelApi(Protocol):
    """The slice of `docker.APIClient` used here. `prune_builds()` of SDK 5.0.3 takes no args."""

    def containers(self, *, all: bool, filters: dict[str, Any] | None = None) -> list[Any]: ...

    def images(self, *, all: bool) -> list[dict[str, Any]]: ...

    def _url(self, pathfmt: str) -> str: ...

    def _post(self, url: str, *, params: dict[str, str], timeout: float) -> Any: ...

    def _result(self, response: Any, json: bool) -> Any: ...


class DiskClientLike(Protocol):
    @property
    def images(self) -> _ImageCollection: ...

    @property
    def volumes(self) -> _VolumeCollection: ...

    @property
    def api(self) -> _LowLevelApi: ...


class DiskSdkOps(ABC):
    """Mixin of `DockerSdkControl`: the disk operations over the primary engine's client."""

    @property
    @abstractmethod
    def _client(self) -> DiskClientLike: ...

    def inspect_image(self, *, image_id: str) -> LiveImage | None:
        """In use means a container (any state) whose `ImageID` equals the id.

        This is the definition the disk report uses (`disk_rules`), so the planner and the
        executor never disagree. The `ancestor` filter would also match child images.
        `has_children`: some image lists this id as its `ParentId`.
        """
        with _sdk_errors(action="inspect", noun="image", on_missing=OnMissing.NONE):
            client = self._client
            image = client.images.get(image_id)
            api = client.api
            used = {str(c.get("ImageID")) for c in api.containers(all=True)}
            children = any(r.get("ParentId") == image.id for r in api.images(all=True))
            return LiveImage(
                id=image.id, in_use=image.id in used, tags=tuple(image.tags), has_children=children
            )
        return None

    def resolve_image(self, *, ref: str) -> str | None:
        """The id a tag points to right now, None if the tag does not exist."""
        with _sdk_errors(action="resolve", noun="image", on_missing=OnMissing.NONE):
            return self._client.images.get(ref).id
        return None

    def remove_image(self, *, ref: str) -> None:
        """Remove a tag or an id; `noprune=False` so untagged parents go with it."""
        with _sdk_errors(action="remove", noun="image", on_missing=OnMissing.GONE):
            self._client.images.remove(ref, noprune=False)

    def inspect_volume(self, *, name: str) -> LiveVolume | None:
        """In use means a container (any state) mounts it: filter `volume=<name>`."""
        with _sdk_errors(action="inspect", noun="volume", on_missing=OnMissing.NONE):
            client = self._client
            volume = client.volumes.get(name)
            users = client.api.containers(all=True, filters={"volume": [name]})
            created_at = str(volume.attrs.get("CreatedAt") or "")
            return LiveVolume(name=name, in_use=bool(users), created_at=created_at)
        return None

    def remove_volume(self, *, name: str) -> None:
        with _sdk_errors(action="remove", noun="volume", on_missing=OnMissing.GONE):
            self._client.volumes.get(name).remove()

    def prune_build_cache(self) -> int:
        """Prune with its own long timeout; a 404 is a failure (the endpoint is missing)."""
        api = self._client.api
        with _sdk_errors(action="prune", noun="build cache", on_missing=OnMissing.FAIL):
            try:
                url = api._url(BUILD_PRUNE_PATH)
                reply = api._result(
                    api._post(url, params=BUILD_PRUNE_PARAMS, timeout=BUILD_PRUNE_TIMEOUT_S), True
                )
            except requests.exceptions.ReadTimeout as error:
                raise ControlFailed(PRUNE_TIMEOUT_MESSAGE) from error
            return int(reply.get(SPACE_RECLAIMED_KEY) or 0)
        return 0
