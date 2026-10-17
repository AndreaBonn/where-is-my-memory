import logging
from typing import Any

LOGGER = logging.getLogger(__name__)


def build_actions(*, config: Any, owner_uid: int) -> Any:
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
        owner_uid=owner_uid,
        terminate_timeout_s=config.terminate_timeout_s,
    )
    return ActionSetup(executor=executor, owner_uid=owner_uid)
