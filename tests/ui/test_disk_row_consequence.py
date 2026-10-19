from tests.core.disk_helpers import (
    MB,
    cache,
    devdir,
    docker_disk,
    image,
    report,
    stopped,
    volume,
)
from wimm.core.planning_disk import DISK_PLANNERS, plan_cache_clean
from wimm.model.actions import ActionRequest
from wimm.model.disk import CacheKind, DiskReport
from wimm.model.enums import ActionKind, TargetId
from wimm.ui.disk_model import DiskRowView
from wimm.ui.disk_view import build_disk_sections

MIN_AGE = 90
NODE_MODULES = "/home/u/proj/node_modules"


def rows_of(*, disk: DiskReport, key: str) -> tuple[DiskRowView, ...]:
    sections = build_disk_sections(report=disk, min_age_days=MIN_AGE)
    return tuple(row for section in sections for row in section.rows if section.key.startswith(key))


def plan_text(*, disk: DiskReport, row: DiskRowView) -> str:
    """The first "Cosa succede" line the dialog shows for this row's action ("" if none)."""
    assert row.action_kind is not None
    target_id = None if row.target_id is None else TargetId(row.target_id)
    request = ActionRequest(kind=row.action_kind, target_id=target_id)
    if row.action_kind is ActionKind.CONTAINER_REMOVE:
        # A stopped container is planned as one step of "remove the stopped containers".
        request = ActionRequest(kind=ActionKind.CONTAINERS_PRUNE_STOPPED)
    if row.action_kind is ActionKind.CACHE_CLEAN:
        drafts = plan_cache_clean(request=request, report=disk)
    else:
        drafts = DISK_PLANNERS[request.kind](request=request, report=disk)
    consequences = drafts[0].assessed.consequences
    return consequences[0] if consequences else ""


def test_trash_row_carries_the_dialog_consequence() -> None:
    disk = report(caches=(cache(kind=CacheKind.TRASH, size=MB),))
    (row,) = rows_of(disk=disk, key="trash")
    assert row.consequence
    assert row.consequence == plan_text(disk=disk, row=row)


def test_devdir_row_carries_the_dialog_consequence_naming_the_rebuild() -> None:
    disk = report(devdirs=(devdir(path=NODE_MODULES, marker="package.json"),))
    (row,) = rows_of(disk=disk, key="devdirs")
    assert row.consequence == plan_text(disk=disk, row=row)
    assert "npm" in row.consequence


def test_image_row_carries_the_dialog_consequence() -> None:
    disk = report(docker=docker_disk(images=(image(char="a"),)))
    (row,) = rows_of(disk=disk, key="images")
    assert row.consequence
    assert row.consequence == plan_text(disk=disk, row=row)


def test_dangling_image_row_has_the_same_text_as_its_plan() -> None:
    disk = report(docker=docker_disk(images=(image(char="b", tags=(), dangling=True),)))
    (row,) = rows_of(disk=disk, key="images")
    assert row.consequence == plan_text(disk=disk, row=row)


def test_container_row_carries_the_dialog_consequence() -> None:
    disk = report(docker=docker_disk(containers=(stopped(cid="c"),)))
    (row,) = rows_of(disk=disk, key="containers")
    assert row.consequence
    assert row.consequence == plan_text(disk=disk, row=row)


def test_volume_row_carries_the_dialog_consequence() -> None:
    disk = report(docker=docker_disk(volumes=(volume(name="data"),)))
    (row,) = rows_of(disk=disk, key="volumes")
    assert row.consequence
    assert row.consequence == plan_text(disk=disk, row=row)


def test_build_cache_row_carries_the_dialog_consequence() -> None:
    disk = report(docker=docker_disk(build_cache_size=MB, build_cache_reclaimable=MB))
    (row,) = rows_of(disk=disk, key="build_cache")
    assert row.consequence
    assert row.consequence == plan_text(disk=disk, row=row)


def test_rows_without_an_action_have_no_consequence() -> None:
    docker = docker_disk(
        images=(image(char="d", in_use=True),),
        volumes=(volume(name="busy", ref_count=1),),
        build_cache_size=MB,
        build_cache_reclaimable=0,
    )
    disk = report(docker=docker)
    for key in ("images", "volumes", "build_cache"):
        (row,) = rows_of(disk=disk, key=key)
        assert row.action_kind is None
        assert row.consequence == ""
