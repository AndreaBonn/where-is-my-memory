"""Every Disco action and row must tell the user what happens: no empty consequence."""

import pytest

from tests.core.disk_helpers import (
    cache,
    devdir,
    docker_disk,
    image,
    report,
    sha,
    stopped,
    volume,
)
from wimm.core.item_tools import ITEM_ONLY_KINDS
from wimm.core.planning_disk import DISK_PLANNERS, plan_cache_clean
from wimm.model.actions import ActionRequest
from wimm.model.disk import CacheKind, DiskReport
from wimm.model.enums import ActionKind, TargetId
from wimm.ui.disk_view import build_disk_sections

MIN_AGE = 90
VOLUME_NAME = "data"
DEVDIR_PATH = "/home/u/proj/node_modules"


def _full_report() -> DiskReport:
    docker = docker_disk(
        images=(
            image(char="a"),
            image(char="b", local_build=True),
            image(char="c", tags=(), dangling=True),
        ),
        volumes=(volume(name=VOLUME_NAME),),
        containers=(stopped(cid="d"),),
        build_cache_size=1,
    )
    return report(
        docker=docker,
        caches=tuple(cache(kind=kind, ino=index) for index, kind in enumerate(CacheKind)),
        devdirs=(
            devdir(path=DEVDIR_PATH, marker="package.json"),
            devdir(path="/home/u/proj/target", marker=""),
        ),
    )


def _requests() -> list[ActionRequest]:
    """One request per (action, target) pair a Disco row or section can ask the planner for."""
    requests = [
        ActionRequest(kind=ActionKind.IMAGE_REMOVE, target_id=TargetId(sha(char))) for char in "abc"
    ]
    requests += [
        ActionRequest(kind=ActionKind.IMAGES_PRUNE_DANGLING),
        ActionRequest(kind=ActionKind.IMAGES_PRUNE_UNUSED),
        ActionRequest(kind=ActionKind.CONTAINERS_PRUNE_STOPPED),
        ActionRequest(kind=ActionKind.BUILDER_PRUNE),
        ActionRequest(kind=ActionKind.VOLUME_REMOVE, target_id=TargetId(VOLUME_NAME)),
        ActionRequest(kind=ActionKind.TRASH_EMPTY),
        ActionRequest(kind=ActionKind.DEVDIR_DELETE, target_id=TargetId(DEVDIR_PATH)),
        ActionRequest(kind=ActionKind.DEVDIR_DELETE, target_id=TargetId("/home/u/proj/target")),
    ]
    return requests


def test_every_disk_planner_action_is_covered_by_the_requests() -> None:
    assert {request.kind for request in _requests()} == set(DISK_PLANNERS)


@pytest.mark.parametrize("request_", _requests(), ids=lambda r: f"{r.kind.value}:{r.target_id}")
def test_planner_drafts_each_carry_a_consequence(request_: ActionRequest) -> None:
    drafts = DISK_PLANNERS[request_.kind](request=request_, report=_full_report())

    assert drafts
    assert all(draft.assessed.consequences and draft.assessed.consequences[0] for draft in drafts)


@pytest.mark.parametrize("kind", [k for k in CacheKind if k not in ITEM_ONLY_KINDS])
def test_cache_clean_draft_carries_a_consequence(kind: CacheKind) -> None:
    if kind is CacheKind.TRASH:
        pytest.skip("the trash is emptied by trash_empty, covered above")
    request_ = ActionRequest(kind=ActionKind.CACHE_CLEAN, target_id=TargetId(kind.value))

    (draft,) = plan_cache_clean(
        request=request_, report=_full_report(), which=lambda name: f"/usr/bin/{name}"
    )

    assert draft.assessed.consequences[0]


def test_every_disco_row_with_an_action_shows_a_consequence() -> None:
    sections = build_disk_sections(report=_full_report(), min_age_days=MIN_AGE)
    rows = [row for section in sections for row in section.rows if row.action_kind is not None]

    assert len(rows) >= len(CacheKind) + 3
    assert [row.title for row in rows if not row.consequence] == []
