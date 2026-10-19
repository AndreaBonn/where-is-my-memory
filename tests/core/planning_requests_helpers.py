from dataclasses import replace

from tests.core.disk_helpers import docker_disk, report, volume
from wimm.core.planning import PlanningContext
from wimm.model.actions import (
    ActionRequest,
)
from wimm.model.enums import ActionKind, GroupId, TargetId


def _stop(gid: str, excluded: frozenset[str] = frozenset()) -> ActionRequest:
    return ActionRequest(kind=ActionKind.GROUP_STOP, group_id=GroupId(gid), excluded_ids=excluded)


def _terminate(pid: int) -> ActionRequest:
    return ActionRequest(kind=ActionKind.PROCESS_TERMINATE, target_id=TargetId(str(pid)))


ORPHANS = report(docker=docker_disk(volumes=(volume(name="pgdata"), volume(name="v"))))


def _with_volumes(base: PlanningContext) -> PlanningContext:
    return replace(base, disk_report=ORPHANS)
