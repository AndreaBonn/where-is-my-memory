import logging
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)


def _disk_fs(*, config: Any, owner_uid: int, home: Path | None) -> Any:
    """Folder, cache and trash control: real commands, real process list, one home."""
    from wimm.service.fs_controls import DiskFsControl, PsutilCwds, SubprocessRunner

    return DiskFsControl(
        home=Path.home() if home is None else home,
        roots=config.devdirs_roots,
        min_age_days=config.devdirs_min_age_days,
        runner=SubprocessRunner(),
        cwds=PsutilCwds(owner_uid=owner_uid),
    )


def build_actions(*, config: Any, owner_uid: int, home: Path | None = None) -> Any:
    from wimm.service.actions import ActionSetup
    from wimm.service.compose import DockerComposeControl
    from wimm.service.controls import DockerSdkControl, PsutilProcessControl
    from wimm.service.executor import PlanExecutor

    try:
        containers = DockerSdkControl.from_env()
    except Exception:
        LOGGER.warning("Docker client unavailable, container actions disabled", exc_info=True)
        containers = None
    try:
        compose = DockerComposeControl.from_env()
    except Exception:
        LOGGER.warning("Docker compose unavailable, project actions disabled", exc_info=True)
        compose = None
    processes = PsutilProcessControl(
        owner_uid=owner_uid, extra_protected_names=config.extra_protected_names
    )
    executor = PlanExecutor(
        processes=processes,
        containers=containers,
        compose=compose,
        disk_fs=_disk_fs(config=config, owner_uid=owner_uid, home=home),
        owner_uid=owner_uid,
        terminate_timeout_s=config.terminate_timeout_s,
    )
    return ActionSetup(executor=executor, owner_uid=owner_uid)
