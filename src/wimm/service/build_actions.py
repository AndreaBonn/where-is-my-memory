import logging
import os
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)
# The Docker SDK's default client timeout, kept now that the controls run on pool clients.
ENGINE_TIMEOUT_S = 60


def _disk_fs(*, config: Any, owner_uid: int, home: Path | None) -> Any:
    """Folder, cache and trash control: real commands, real process list, one home."""
    from wimm.collectors.cache_table import read_cache_table
    from wimm.service.fs_controls import DiskFsControl, PsutilCwds, SubprocessRunner

    base = Path.home() if home is None else home
    return DiskFsControl(
        home=base,
        caches=read_cache_table(environ=os.environ, home=base, roots=config.devdirs_roots),
        roots=config.devdirs_roots,
        min_age_days=config.devdirs_min_age_days,
        runner=SubprocessRunner(),
        cwds=PsutilCwds(owner_uid=owner_uid),
    )


def build_actions(*, config: Any, owner_uid: int, home: Path | None = None) -> Any:
    from wimm.collectors.docker_engines import local_pool
    from wimm.service.actions import ActionSetup
    from wimm.service.compose import DockerComposeControl, resolve_docker_binary
    from wimm.service.controls import DockerSdkControl, PsutilProcessControl
    from wimm.service.executor import PlanExecutor

    engines = local_pool(timeout=ENGINE_TIMEOUT_S)
    containers = DockerSdkControl(engines=engines)
    try:
        compose = DockerComposeControl(engines=engines, docker_bin=resolve_docker_binary())
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
    return ActionSetup(
        executor=executor, owner_uid=owner_uid, engine_identities=containers.engine_identities
    )
