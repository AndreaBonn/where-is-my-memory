from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from wimm.collectors.desktop_entries import DesktopEntry
from wimm.collectors.project_roots import ProjectRootResolver
from wimm.config import Config
from wimm.core.activity import ActivityConfig
from wimm.core.assemble import Entities
from wimm.core.grouping import GroupDraft, GroupingInput, build_groups
from wimm.paths import UserPaths

from .history import EntityKey


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
