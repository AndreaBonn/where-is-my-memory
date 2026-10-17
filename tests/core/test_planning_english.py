import pytest

from wimm.core.planning import PlanningContext, plan_action
from wimm.model.actions import ActionRequest, Plan
from wimm.model.disk import CacheKind, DiskReport
from wimm.model.enums import ActionKind, Category, PlanId, Risk

from .disk_helpers import MB, cache, docker_disk, image, report
from .planning_helpers import NOW, OWNER_UID, context, group, proc, snapshot

pytestmark = pytest.mark.usefixtures("english")


def _disk_plan(*, kind: ActionKind, disk: DiskReport) -> Plan:
    context = PlanningContext(
        owner_uid=OWNER_UID,
        now=lambda: NOW,
        new_plan_id=lambda: PlanId("p-1"),
        disk_report=disk,
    )
    return plan_action(request=ActionRequest(kind=kind), snapshot=snapshot(), context=context)


def test_trash_empty_asks_to_type_the_english_name() -> None:
    disk = report(caches=(cache(kind=CacheKind.TRASH, size=40 * MB),))

    plan = _disk_plan(kind=ActionKind.TRASH_EMPTY, disk=disk)

    assert plan.risk is Risk.DANGER
    assert plan.confirm_phrase == "Trash"
    assert plan.consequences == ("The files in the trash are permanently deleted.",)


def test_builder_prune_step_is_labelled_in_english() -> None:
    disk = report(docker=docker_disk(build_cache_size=100 * MB))

    plan = _disk_plan(kind=ActionKind.BUILDER_PRUNE, disk=disk)

    assert plan.steps[0].target_label == "Build cache"


def test_truncated_report_note_is_in_english() -> None:
    images = tuple(image(char=f"{n:x}", tags=(), dangling=True) for n in range(1, 201))
    disk = report(docker=docker_disk(images=images, images_truncated=60))

    plan = _disk_plan(kind=ActionKind.IMAGES_PRUNE_DANGLING, disk=disk)

    assert (
        "The report shows the 200 largest items: 60 more remain, "
        "and a new scan is needed after the cleanup."
    ) in plan.consequences


def test_stop_all_idle_labels_the_process_with_its_pid() -> None:
    idle = group(gid="a", category=Category.DEV_SERVER, members=(proc(pid=1),))
    request = ActionRequest(kind=ActionKind.STOP_ALL_IDLE_SAFE)

    plan = plan_action(request=request, snapshot=snapshot(idle), context=context())

    assert [step.target_label for step in plan.steps] == ["node (pid 1)"]
    assert plan.consequences == ("The server stops.",)
