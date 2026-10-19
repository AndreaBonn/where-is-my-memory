from pathlib import Path

from tests.service.fs_fakes import (
    FsRig,
    dir_plan,
)
from wimm.model.enums import ActionKind
from wimm.service.control_protocols import StepStatus

DELETE = ActionKind.DEVDIR_DELETE


def delete_devdir(*, rig: FsRig, folder: Path) -> StepStatus:
    outcomes = rig.executor().execute(plan=dir_plan(kind=DELETE, path=folder))
    return outcomes[0].status


# --- CACHE_CLEAN -----------------------------------------------------------------

CLEAN = ActionKind.CACHE_CLEAN
