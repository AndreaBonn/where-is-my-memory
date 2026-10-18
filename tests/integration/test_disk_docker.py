"""Disk actions against the real daemon, on objects created here and named `wimm-test-*`.

No image is pulled: the tests need `alpine:3` already present (see `docker_targets.connect`).
The test image is a local commit of a container, so it has an id of its own and removing it
never touches `alpine:3`. Nothing here runs a prune.
"""

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime, timedelta
from typing import Any

import docker.errors
import pytest

from tests.integration.docker_targets import IMAGE, TEST_LABELS, connect
from wimm.collectors.docker_engines import FixedEngines
from wimm.model.actions import ActionRequest, ImageFingerprint, Plan, PlanStep, VolumeFingerprint
from wimm.model.enums import ActionKind, PlanId, Risk, TargetId
from wimm.service.control_protocols import StepStatus
from wimm.service.controls import DockerSdkControl, PsutilProcessControl
from wimm.service.errors import TargetChanged
from wimm.service.executor import PlanExecutor

pytestmark = [pytest.mark.integration, pytest.mark.docker]
TEST_PREFIX = "wimm-test"
PLAN_TTL_S = 120


@pytest.fixture
def client() -> Any:
    try:
        return connect()
    except RuntimeError as error:
        pytest.skip(str(error))


@pytest.fixture
def executor(client: Any) -> PlanExecutor:
    return PlanExecutor(
        processes=PsutilProcessControl(owner_uid=os.getuid()),
        containers=DockerSdkControl(engines=FixedEngines(client=client)),
        owner_uid=os.getuid(),
    )


def _step(
    *, kind: ActionKind, label: str, fingerprint: ImageFingerprint | VolumeFingerprint
) -> PlanStep:
    risk = Risk.DANGER if kind is ActionKind.VOLUME_REMOVE else Risk.SAFE
    return PlanStep(order=1, kind=kind, target_label=label, fingerprint=fingerprint, risk=risk)


def _run(*, executor: PlanExecutor, step: PlanStep) -> StepStatus:
    now = datetime.now(UTC)
    plan = Plan(
        plan_id=PlanId("integration-disk-plan"),
        request=ActionRequest(kind=step.kind, target_id=TargetId("target")),
        created_at=now,
        expires_at=now + timedelta(seconds=PLAN_TTL_S),
        steps=(step,),
        consequences=(),
        estimated_reclaim_ram=0,
        estimated_reclaim_disk=0,
        confirm_phrase=step.target_label if step.risk is Risk.DANGER else None,
    )
    return executor.execute(plan=plan)[0].status


def _image_exists(*, client: Any, image_id: str) -> bool:
    try:
        client.images.get(image_id)
    except docker.errors.ImageNotFound:
        return False
    return True


@contextmanager
def _test_image(*, client: Any, suffixes: tuple[str, ...] = ("",)) -> Iterator[Any]:
    """Commit an image tagged `wimm-test:<uuid><suffix>` per suffix; only those tags are removed."""
    base = uuid.uuid4().hex
    tags = [f"{TEST_PREFIX}:{base}{suffix}" for suffix in suffixes]
    source = client.containers.create(IMAGE, ["true"], labels=TEST_LABELS)
    try:
        repository, tag = tags[0].split(":")
        image = source.commit(repository=repository, tag=tag, changes="LABEL wimm.test=1")
    finally:
        source.remove(force=True)
    try:
        for extra in tags[1:]:
            image.tag(*extra.split(":"))
        yield image
    finally:
        for name in tags:
            with suppress(docker.errors.ImageNotFound):
                client.images.remove(name, force=True)


@contextmanager
def _test_volume(*, client: Any) -> Iterator[Any]:
    volume = client.volumes.create(name=f"{TEST_PREFIX}-{uuid.uuid4().hex}", labels=TEST_LABELS)
    try:
        yield volume
    finally:
        with suppress(docker.errors.NotFound):
            volume.remove(force=True)


def test_unused_test_image_is_removed_and_the_source_image_is_untouched(
    client: Any, executor: PlanExecutor
) -> None:
    with _test_image(client=client) as image:
        step = _step(
            kind=ActionKind.IMAGE_REMOVE,
            label=image.id,
            fingerprint=ImageFingerprint(id=image.id),
        )

        assert _run(executor=executor, step=step) is StepStatus.DONE

        assert not _image_exists(client=client, image_id=image.id)
        assert _image_exists(client=client, image_id=IMAGE)


def test_image_with_two_tags_is_removed_without_force(client: Any, executor: PlanExecutor) -> None:
    with _test_image(client=client, suffixes=("-a", "-b")) as image:
        assert len(client.images.get(image.id).tags) == 2
        step = _step(
            kind=ActionKind.IMAGE_REMOVE,
            label=image.id,
            fingerprint=ImageFingerprint(id=image.id),
        )

        assert _run(executor=executor, step=step) is StepStatus.DONE

        assert not _image_exists(client=client, image_id=image.id)
        assert _image_exists(client=client, image_id=IMAGE)


def test_image_used_by_a_stopped_container_is_refused(client: Any, executor: PlanExecutor) -> None:
    with _test_image(client=client) as image:
        holder = client.containers.create(image.id, ["true"], labels=TEST_LABELS)
        try:
            step = _step(
                kind=ActionKind.IMAGE_REMOVE,
                label=image.id,
                fingerprint=ImageFingerprint(id=image.id),
            )

            with pytest.raises(TargetChanged):
                _run(executor=executor, step=step)

            assert _image_exists(client=client, image_id=image.id)
        finally:
            holder.remove(force=True)


def test_orphan_test_volume_is_removed(client: Any, executor: PlanExecutor) -> None:
    with _test_volume(client=client) as volume:
        step = _step(
            kind=ActionKind.VOLUME_REMOVE,
            label=volume.name,
            fingerprint=VolumeFingerprint(name=volume.name, created_at=volume.attrs["CreatedAt"]),
        )

        assert _run(executor=executor, step=step) is StepStatus.DONE

        with pytest.raises(docker.errors.NotFound):
            client.volumes.get(volume.name)


def test_volume_mounted_by_a_test_container_is_refused(client: Any, executor: PlanExecutor) -> None:
    with _test_volume(client=client) as volume:
        holder = client.containers.create(
            IMAGE,
            ["true"],
            labels=TEST_LABELS,
            volumes={volume.name: {"bind": "/data", "mode": "rw"}},
        )
        try:
            step = _step(
                kind=ActionKind.VOLUME_REMOVE,
                label=volume.name,
                fingerprint=VolumeFingerprint(
                    name=volume.name, created_at=volume.attrs["CreatedAt"]
                ),
            )

            with pytest.raises(TargetChanged):
                _run(executor=executor, step=step)

            assert client.volumes.get(volume.name).name == volume.name
        finally:
            holder.remove(force=True)
