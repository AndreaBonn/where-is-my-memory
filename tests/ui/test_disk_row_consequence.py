import pytest

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
from tests.core.planning_helpers import NOW, OWNER_UID, container, group, snapshot
from wimm.core.item_tools import ITEM_ONLY_KINDS
from wimm.core.planning import PlanningContext, plan_action
from wimm.core.row_consequence import join_consequences
from wimm.model.actions import ActionRequest
from wimm.model.disk import CacheKind, DiskReport
from wimm.model.enums import PlanId, TargetId
from wimm.ui.disk_model import DiskRowView
from wimm.ui.disk_view import build_disk_sections

MIN_AGE = 90
NODE_MODULES = "/home/u/proj/node_modules"


def rows_of(*, disk: DiskReport, key: str) -> tuple[DiskRowView, ...]:
    # Every tool is on PATH, as plan_text's `which` says, so no command-only cache is withheld.
    sections = build_disk_sections(report=disk, min_age_days=MIN_AGE, withheld=frozenset())
    return tuple(row for section in sections for row in section.rows if section.key.startswith(key))


def plan_text(*, disk: DiskReport, row: DiskRowView) -> str:
    """The "Cosa succede" text the dialog shows for this row's action, from the real planner.

    Cache, trash and devdir planners call row_consequence themselves, so for those rows the
    equality checks the wiring; the pinned literals below check the text itself.
    """
    assert row.action_kind is not None
    target_id = None if row.target_id is None else TargetId(row.target_id)
    request = ActionRequest(kind=row.action_kind, target_id=target_id)
    # A stopped container is planned from the snapshot, as the app does for the row's button.
    exited = tuple(container(cid=c.id, state=c.state) for c in disk.docker.stopped_containers)
    context = PlanningContext(
        owner_uid=OWNER_UID,
        now=lambda: NOW,
        new_plan_id=lambda: PlanId("p"),
        disk_report=disk,
        which=lambda name: f"/usr/bin/{name}",
    )
    plan = plan_action(
        request=request, snapshot=snapshot(group(gid="g", members=exited)), context=context
    )
    return join_consequences(consequences=plan.consequences)


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
    assert row.consequence
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


@pytest.mark.parametrize(
    "kind", [k for k in CacheKind if k is not CacheKind.TRASH and k not in ITEM_ONLY_KINDS]
)
def test_cache_row_carries_the_dialog_consequence(kind: CacheKind) -> None:
    disk = report(caches=(cache(kind=kind, size=MB),))
    (row,) = rows_of(disk=disk, key="caches")
    assert row.consequence
    assert row.consequence == plan_text(disk=disk, row=row)


def test_huggingface_row_says_the_models_are_downloaded_again() -> None:
    disk = report(caches=(cache(kind=CacheKind.HUGGINGFACE, size=MB),))
    (row,) = rows_of(disk=disk, key="caches")
    expected = "Modelli di HuggingFace: si riscaricano quando servono, anche diversi GB."
    assert row.consequence == expected == plan_text(disk=disk, row=row)


def test_devdir_row_names_npm_install_as_the_rebuild() -> None:
    disk = report(devdirs=(devdir(path=NODE_MODULES, marker="package.json"),))
    (row,) = rows_of(disk=disk, key="devdirs")
    expected = "Per usare di nuovo il progetto serve ricostruire la cartella con npm install."
    assert row.consequence == expected == plan_text(disk=disk, row=row)


@pytest.mark.parametrize("kind", sorted(ITEM_ONLY_KINDS, key=str))
def test_an_item_only_cache_row_has_no_action_and_no_consequence(kind: CacheKind) -> None:
    # The planner refuses a whole-cache clean of these kinds: the row must not offer one.
    disk = report(caches=(cache(kind=kind, size=MB),))
    (row,) = rows_of(disk=disk, key="caches")
    assert row.action_kind is None
    assert row.consequence == ""
