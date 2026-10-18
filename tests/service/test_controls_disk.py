from typing import Any

import docker.errors
import pytest
import requests.exceptions

from tests.service.engine_fakes import FakeProvider, engine_at
from wimm.collectors.docker_engines import FixedEngines
from wimm.service.controls import DockerSdkControl
from wimm.service.errors import ControlFailed, TargetGone

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


def test_image_used_by_a_stopped_container_is_in_use() -> None:
    sdk, _ = control(containers=[{"ImageID": IMAGE_ID}, {"ImageID": "sha256:other"}])

    live = sdk.inspect_image(image_id=IMAGE_ID)

    assert live is not None and live.in_use is True


def test_image_used_only_by_other_images_containers_is_not_in_use() -> None:
    sdk, _ = control(containers=[{"ImageID": "sha256:other"}])

    live = sdk.inspect_image(image_id=IMAGE_ID)

    assert live is not None and live.in_use is False


def test_image_reports_its_tags() -> None:
    sdk, client = control()
    client.images.known[IMAGE_ID] = FakeImage(image_id=IMAGE_ID, tags=["a:1", "b:2"])

    live = sdk.inspect_image(image_id=IMAGE_ID)

    assert live is not None and live.tags == ("a:1", "b:2")


def test_missing_image_is_none() -> None:
    sdk, _ = control()

    assert sdk.inspect_image(image_id="sha256:nope") is None


def test_remove_image_does_not_skip_pruning_of_untagged_parents() -> None:
    sdk, client = control()

    sdk.remove_image(ref=IMAGE_ID)

    assert client.images.removed == [(IMAGE_ID, False)]


def test_volume_mounted_by_a_container_is_in_use_and_the_filter_is_the_name() -> None:
    sdk, client = control(containers=[{"Volumes": ["busy"]}])

    busy = sdk.inspect_volume(name="busy")
    free = sdk.inspect_volume(name="data")

    assert busy is not None and busy.in_use is True
    assert free is not None and free.in_use is False
    assert client.api.filters == [{"volume": ["busy"]}, {"volume": ["data"]}]


def test_missing_volume_is_none_and_removal_of_it_is_target_gone() -> None:
    sdk, client = control()

    assert sdk.inspect_volume(name="nope") is None
    with pytest.raises(TargetGone):
        sdk.remove_volume(name="nope")
    sdk.remove_volume(name="data")
    assert client.volumes.removed == ["data"]


def test_volume_reports_its_created_at_verbatim() -> None:
    sdk, _ = control()

    live = sdk.inspect_volume(name="data")

    assert live is not None and live.created_at == CREATED_AT


def test_removal_of_a_missing_image_is_target_gone() -> None:
    sdk, client = control()

    with pytest.raises(TargetGone):
        sdk.remove_image(ref="sha256:nope")
    assert client.images.removed == []


def test_image_with_a_child_image_reports_has_children() -> None:
    sdk, client = control()
    client.api.image_records = [
        {"Id": "sha256:child", "ParentId": IMAGE_ID},
        {"Id": IMAGE_ID, "ParentId": ""},
    ]

    live = sdk.inspect_image(image_id=IMAGE_ID)

    assert live is not None and live.has_children is True


def test_image_that_is_nobodys_parent_has_no_children() -> None:
    sdk, client = control()
    client.api.image_records = [{"Id": IMAGE_ID, "ParentId": ""}, {"Id": "x", "ParentId": "y"}]

    live = sdk.inspect_image(image_id=IMAGE_ID)

    assert live is not None and live.has_children is False


def test_resolve_image_returns_the_id_a_tag_points_to_now() -> None:
    sdk, client = control()
    client.images.known[IMAGE_ID] = FakeImage(image_id=IMAGE_ID, tags=["a:1"])

    assert sdk.resolve_image(ref="a:1") == IMAGE_ID
    assert sdk.resolve_image(ref="a:2") is None


def test_build_cache_prune_asks_for_all_records_and_returns_space_reclaimed() -> None:
    sdk, client = control(reclaimed=1234)

    assert sdk.prune_build_cache() == 1234
    assert client.api.posts == [("http://daemon/build/prune", {"all": "true"}, 600)]


def test_build_prune_waits_longer_than_the_client_default() -> None:
    default_client_timeout_s = 60
    sdk, client = control(reclaimed=1)

    sdk.prune_build_cache()

    passed_timeout_s = client.api.posts[0][2]
    assert passed_timeout_s == 600
    assert passed_timeout_s > default_client_timeout_s


def test_sdk_failure_while_pruning_becomes_control_failed() -> None:
    sdk, _ = control(failure=docker.errors.APIError("daemon busy"))

    with pytest.raises(ControlFailed, match="build cache"):
        sdk.prune_build_cache()


def test_build_prune_timeout_says_the_result_is_unknown() -> None:
    sdk, _ = control(failure=requests.exceptions.ReadTimeout("read timed out"))

    with pytest.raises(ControlFailed) as raised:
        sdk.prune_build_cache()

    assert "still be freeing space" in raised.value.message
    assert "unknown" in raised.value.message


def test_build_prune_not_found_is_a_failure_not_a_silent_success() -> None:
    sdk, _ = control(failure=docker.errors.NotFound("404 page not found"))

    with pytest.raises(ControlFailed, match="build cache"):
        sdk.prune_build_cache()


def test_disk_operations_use_the_primary_engine_only() -> None:
    primary = FakeClient(containers=[{"ImageID": IMAGE_ID}])
    other = FakeClient(containers=[])
    provider = FakeProvider(
        engines=(engine_at(path="/a.sock", client=primary), engine_at(path="/b.sock", client=other))
    )

    live = DockerSdkControl(engines=provider).inspect_image(image_id=IMAGE_ID)

    assert live is not None and live.in_use is True  # seen on the primary, not on the other


class ChangingPrimary:
    """A provider whose primary engine is another one at every refresh."""

    def __init__(self, *, clients: list[FakeClient]) -> None:
        self._engines = [
            engine_at(path=f"/{index}.sock", client=client) for index, client in enumerate(clients)
        ]
        self.refreshes = 0

    def refresh(self) -> Any:
        engine = self._engines[min(self.refreshes, len(self._engines) - 1)]
        self.refreshes += 1
        return FakeProvider(engines=(engine,)).refresh()

    def discard(self, *, engine: Any) -> None:
        return None


def test_one_operation_resolves_the_engine_once() -> None:
    first = FakeClient(containers=[{"ImageID": IMAGE_ID}])
    second = FakeClient(containers=[])
    provider = ChangingPrimary(clients=[first, second])

    live = DockerSdkControl(engines=provider).inspect_image(image_id=IMAGE_ID)

    assert provider.refreshes == 1
    assert live is not None and live.in_use is True
