import pytest

from tests.core.disk_helpers import (
    MB,
    SCANNED_AT,
    cache,
    devdir,
    report,
)
from tests.core.planning_disk_helpers import _plan
from wimm.core.disk_rules import unavailable_docker
from wimm.core.risk import RiskTarget
from wimm.core.row_consequence import row_consequence
from wimm.model.actions import (
    DirFingerprint,
)
from wimm.model.disk import CacheKind, DiskReport
from wimm.model.enums import ActionKind, Risk
from wimm.model.errors import InvalidRequest


def test_cache_clean_uses_the_directory_fingerprint_of_the_named_cache() -> None:
    uv = cache(kind=CacheKind.UV, size=3 * MB, ino=5, dev=9)
    disk = report(caches=(uv, cache(kind=CacheKind.NPM)))

    plan = _plan(kind=ActionKind.CACHE_CLEAN, disk=disk, target="uv")

    assert plan.steps[0].fingerprint == DirFingerprint(realpath=uv.path, st_ino=5, st_dev=9)
    assert plan.risk is Risk.SAFE
    assert plan.estimated_reclaim_disk == 3 * MB


def test_cache_clean_refuses_trash_and_missing_caches() -> None:
    disk = report(caches=(cache(kind=CacheKind.TRASH), cache(kind=CacheKind.UV)))

    with pytest.raises(InvalidRequest):
        _plan(kind=ActionKind.CACHE_CLEAN, disk=disk, target="trash")
    with pytest.raises(InvalidRequest):
        _plan(kind=ActionKind.CACHE_CLEAN, disk=disk, target="pip")


def test_trash_empty_is_danger_with_the_trash_label_as_phrase() -> None:
    trash = cache(kind=CacheKind.TRASH, size=40 * MB)

    plan = _plan(kind=ActionKind.TRASH_EMPTY, disk=report(caches=(trash,)))

    assert plan.risk is Risk.DANGER
    assert plan.confirm_phrase == "Cestino"
    assert plan.steps[0].fingerprint == DirFingerprint(realpath=trash.path, st_ino=11, st_dev=2049)
    assert plan.estimated_reclaim_disk == 40 * MB


@pytest.mark.parametrize(
    ("kind", "target"),
    [
        (ActionKind.IMAGES_PRUNE_DANGLING, None),
        (ActionKind.IMAGES_PRUNE_UNUSED, None),
        (ActionKind.CONTAINERS_PRUNE_STOPPED, None),
        (ActionKind.BUILDER_PRUNE, None),
        (ActionKind.TRASH_EMPTY, None),
        (ActionKind.DEVDIR_DELETE, "/w/old/node_modules"),
        (ActionKind.CACHE_CLEAN, "uv"),
    ],
)
def test_disk_actions_without_a_report_are_refused(kind: ActionKind, target: str | None) -> None:
    with pytest.raises(InvalidRequest, match="report"):
        _plan(kind=kind, disk=None, target=target)


def test_docker_actions_with_docker_unavailable_name_the_reason() -> None:
    disk = DiskReport(
        scanned_at=SCANNED_AT,
        docker=unavailable_docker(error="daemon stopped"),
        caches=(),
        devdirs=(),
    )

    with pytest.raises(InvalidRequest, match="daemon stopped"):
        _plan(kind=ActionKind.IMAGES_PRUNE_UNUSED, disk=disk)


def test_volume_remove_without_a_report_is_refused() -> None:
    # Without a report there is no creation time, and the executor would refuse anyway.
    with pytest.raises(InvalidRequest):
        _plan(kind=ActionKind.VOLUME_REMOVE, disk=None, target="pgdata")


@pytest.mark.parametrize(
    ("path", "marker", "command"),
    [
        ("/w/rs/target", "Cargo.toml", "cargo build"),
        ("/w/java/target", "pom.xml", "mvn package"),
        ("/w/web/node_modules", "", "npm install"),
    ],
)
def test_devdir_delete_plan_tells_how_to_rebuild_that_kind_of_folder(
    path: str, marker: str, command: str
) -> None:
    disk = report(devdirs=(devdir(path=path, marker=marker),))

    plan = _plan(kind=ActionKind.DEVDIR_DELETE, disk=disk, target=path)

    assert plan.consequences == (
        f"Per usare di nuovo il progetto serve ricostruire la cartella con {command}.",
    )


@pytest.mark.parametrize("kind", [CacheKind.UV, CacheKind.MAVEN, CacheKind.OLLAMA])
def test_plan_cache_clean_consequence_matches_row_consequence(kind: CacheKind) -> None:
    disk = report(caches=(cache(kind=kind),))

    plan = _plan(kind=ActionKind.CACHE_CLEAN, disk=disk, target=kind.value)

    expected = row_consequence(
        action=ActionKind.CACHE_CLEAN, target=RiskTarget(kind="cache", cache_kind=kind)
    )
    assert plan.consequences == (expected,)


def test_plan_devdir_delete_consequence_matches_row_consequence() -> None:
    disk = report(devdirs=(devdir(path="/w/rs/target", marker="Cargo.toml"),))

    plan = _plan(kind=ActionKind.DEVDIR_DELETE, disk=disk, target="/w/rs/target")

    expected = row_consequence(
        action=ActionKind.DEVDIR_DELETE,
        target=RiskTarget(kind="devdir"),
        folder_name="target",
        marker="Cargo.toml",
    )
    assert plan.consequences == (expected,)
