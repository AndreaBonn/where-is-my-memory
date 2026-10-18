import logging
import os
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from wimm.collectors.cache_table import read_cache_table
from wimm.collectors.desktop_entries import DesktopEntry
from wimm.collectors.project_roots import ProjectRootResolver
from wimm.config import Config
from wimm.core.activity import ActivityConfig
from wimm.core.assemble import Entities
from wimm.core.cache_catalog import CacheResolution
from wimm.core.grouping import GroupDraft, GroupingInput, build_groups
from wimm.paths import UserPaths

from .history import EntityKey

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SamplerEnvironment:
    paths: UserPaths
    own_pid: int
    uid: int
    home: Path
    persisted_last_active: Mapping[EntityKey, datetime] = field(default_factory=dict)


def activity_config(*, config: Config) -> ActivityConfig:
    """The activity thresholds and window a configuration asks for."""
    return ActivityConfig(
        window_s=config.activity_window_s,
        interval_s=config.sample_interval_s,
        cpu_threshold_pct=config.cpu_active_threshold_pct,
        net_threshold_bps=config.net_active_threshold_bps,
    )


def group_entities(
    *, entities: Entities, environment: SamplerEnvironment, desktop: Mapping[str, DesktopEntry]
) -> tuple[GroupDraft, ...]:
    resolver = ProjectRootResolver(is_marker=Path.exists, home=environment.home)
    roots = {
        proc.cwd: str(resolver.resolve(cwd=Path(proc.cwd)))
        for proc, _ in entities.processes.values()
        if proc.cwd is not None
    }
    return build_groups(
        grouping=GroupingInput(
            pairs=tuple(entities.processes.values()),
            containers=tuple(entities.containers.values()),
            project_root_by_cwd=roots,
            desktop_name_by_appid={key: item.name for key, item in desktop.items()},
            own_home=str(environment.home),
            own_uid=environment.uid,
            listen_ports_by_pid=entities.listen_ports_by_pid,
        )
    )


def resolve_cache_table(
    *, home: Path, roots: Collection[Path], environ: Mapping[str, str] | None = None
) -> CacheResolution:
    """Where each cache is, from the real disk and the environment (R12).

    The caches the environment points at but that are refused are logged with their type and
    reason; the value is left out, it is a path the user typed.
    """
    table = read_cache_table(
        environ=os.environ if environ is None else environ, home=home, roots=roots
    )
    for rejected in table.rejected:
        LOGGER.info("Cache %s ignored: %s", rejected.kind.value, rejected.reason.value)
    return table
