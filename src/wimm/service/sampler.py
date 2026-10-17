import logging
import os
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

from wimm.collectors import CollectorResult
from wimm.collectors.desktop_entries import DesktopEntry
from wimm.collectors.docker_source import DockerSample
from wimm.config import Config
from wimm.core import constants as c
from wimm.core.activity import ActivityInputs, EntitySample, assess_activity, last_active_at
from wimm.core.assemble import (
    AssemblyInput,
    Entities,
    SystemState,
    Thresholds,
    UserState,
    Verdicts,
    assemble_snapshot,
)
from wimm.core.categorize import CategorizationContext, categorize_process
from wimm.core.grouping import GroupDraft
from wimm.model.enums import ActivityState, Category, MetricsSource
from wimm.model.memory import DiskUsage
from wimm.model.raw import MemInfo, RawProcess
from wimm.model.snapshot import ActivityAssessment, DockerStatus, Snapshot
from wimm.paths import UserPaths

from .history import EntityKey, LastActiveTracker, SampleHistory
from .sampler_collectors import Collectors as Collectors
from .sampler_collectors import default_collectors as default_collectors
from .sampler_environment import SamplerEnvironment as SamplerEnvironment
from .sampler_environment import activity_config, group_entities
from .sampler_steps import ListenPorts, ProcessCycle, ProcessSamples, identity

LOGGER = logging.getLogger(__name__)
MICROSECONDS_PER_SECOND = 1_000_000


def wall_clock() -> datetime:
    return datetime.now(tz=UTC)


def default_environment(*, paths: UserPaths) -> SamplerEnvironment:
    return SamplerEnvironment(paths=paths, own_pid=os.getpid(), uid=os.getuid(), home=Path.home())


class Sampler:
    def __init__(
        self,
        *,
        collectors: Collectors,
        environment: SamplerEnvironment,
        config: Config,
        clock: Callable[[], datetime] = wall_clock,
    ) -> None:
        self.collectors, self.environment, self.settings, self.clock = (
            collectors,
            environment,
            config,
            clock,
        )
        self.monitor_started_at = clock()
        self.history = SampleHistory(
            window_s=config.activity_window_s, interval_s=config.sample_interval_s
        )
        self._last_active = LastActiveTracker(persisted=environment.persisted_last_active)
        self._cpu = ProcessSamples()
        self._process_warning = False
        self._ports = ListenPorts()
        self._mem: MemInfo | None = None
        self._disks: tuple[DiskUsage, ...] = ()
        self._activity = activity_config(config=config)
        self._user = UserState()
        self._reclaimable_disk = 0

    def apply_config(self, *, config: Config) -> None:
        """Adopt a new configuration from the next cycle on.

        Runs on the sampler worker: the history is not thread-safe, so it must not be
        resized while a cycle reads it.
        """
        self.settings = config
        self._activity = activity_config(config=config)
        self.history.resize(window_s=config.activity_window_s, interval_s=config.sample_interval_s)

    def apply_user_state(self, *, user: UserState) -> None:
        """Adopt the user's snoozes and ignores from the next cycle on (worker only)."""
        self._user = user

    def apply_reclaimable_disk(self, *, reclaimable_disk: int) -> None:
        """Adopt the safe-to-free disk bytes of the latest disk scan (worker only)."""
        self._reclaimable_disk = reclaimable_disk

    def export_last_active(self) -> Mapping[EntityKey, datetime]:
        """Last-active instants to persist; safe to call from any thread."""
        return self._last_active.export(now=self.clock(), retention_s=c.LAST_ACTIVE_RETENTION_S)

    def run_cycle(self) -> Snapshot:
        started = monotonic()
        try:
            return self._run_cycle()
        finally:
            LOGGER.debug("Sampling cycle duration %.6f s", monotonic() - started)

    def _run_cycle(self) -> Snapshot:
        processes = self._collect_processes()
        sockets = self.collectors.sockets()
        docker = self.collectors.docker()
        mem, disks = self.collectors.meminfo(), self.collectors.disks()
        self._mem = mem.data if mem.data is not None else self._mem
        self._disks = disks.data or self._disks
        if self._mem is None or not self._disks:
            raise RuntimeError("Memory and disk counters are not ready")
        now = self.clock()
        ports = self._ports.collect(processes=processes, sockets=sockets)
        desktop = self.collectors.desktop().data
        entities = self._entities(processes=processes, ports=ports, docker=docker, desktop=desktop)
        drafts = group_entities(entities=entities, environment=self.environment, desktop=desktop)
        cycle = ProcessCycle(
            processes={p.pid: p for p in processes},
            ports=ports,
            sockets=None if sockets.error else sockets.data,
            now=now,
        )
        verdicts = self._verdicts(entities=entities, cycle=cycle)
        status = (
            DockerStatus(available=False, error=docker.error)
            if docker.error
            else docker.data.status
        )
        return self._assemble(
            drafts=drafts, entities=entities, verdicts=verdicts, system=(now, status)
        )

    def _collect_processes(self) -> tuple[RawProcess, ...]:
        result = self.collectors.processes()
        if result.error and not result.data:
            raise RuntimeError(f"Process collection failed: {result.error}")
        if result.error and not self._process_warning:
            LOGGER.warning("Partial process collection: %s", result.error)
        self._process_warning = bool(result.error)
        return result.data

    def _entities(
        self,
        *,
        processes: tuple[RawProcess, ...],
        ports: Mapping[int, frozenset[int]],
        docker: CollectorResult[DockerSample],
        desktop: Mapping[str, DesktopEntry],
    ) -> Entities:
        categories = {key: item.categories for key, item in desktop.items()}
        context = CategorizationContext(
            own_uid=self.environment.uid,
            own_pid=self.environment.own_pid,
            processes={p.pid: p for p in processes},
            listen_ports_by_pid=ports,
            extra_protected_names=self.settings.extra_protected_names,
            desktop_categories=categories,
        )
        pairs = [(proc, categorize_process(proc=proc, context=context)) for proc in processes]
        return Entities(
            processes={
                proc.pid: (proc, decision)
                for proc, decision in pairs
                if decision.category is not None
            },
            containers={} if docker.error else {item.id: item for item in docker.data.containers},
            listen_ports_by_pid=ports,
            desktop_categories=categories,
        )

    def _record_samples(self, *, entities: Entities, cycle: ProcessCycle) -> None:
        self._cpu.prepare(cycle=cycle)
        samples: dict[EntityKey, EntitySample] = {
            key: self._cpu.sample(proc=proc, cycle=cycle)
            for proc, _ in entities.processes.values()
            if (key := identity(proc=proc)) is not None
        }
        samples.update(
            {
                item.id: EntitySample(
                    taken_at=cycle.now,
                    cpu_time_s=None
                    if item.metrics_source is MetricsSource.UNAVAILABLE
                    else item.cpu_usage_usec / MICROSECONDS_PER_SECOND,
                    net_bytes=item.net_bytes,
                )
                for item in entities.containers.values()
            }
        )
        self.history.append(cycle_samples=samples)
        self._cpu.finish(processes=cycle.processes)

    def _verdicts(self, *, entities: Entities, cycle: ProcessCycle) -> Verdicts:
        self._record_samples(entities=entities, cycle=cycle)
        self._last_active.begin_cycle()
        by_pid = {
            pid: self._assess(
                key=identity(proc=proc),
                category=decision.category,
                now=cycle.now,
                ports=cycle.subtree_ports[pid],
            )
            for pid, (proc, decision) in entities.processes.items()
        }
        by_container = {
            key: self._assess(key=key, category=Category.CONTAINER, now=cycle.now)
            for key in entities.containers
        }
        return Verdicts(by_pid=by_pid, by_container=by_container)

    def _assess(
        self,
        *,
        key: EntityKey | None,
        category: Category | None,
        now: datetime,
        ports: frozenset[int] = frozenset(),
    ) -> ActivityAssessment:
        inputs = self._inputs_for(key=key, category=category, now=now, ports=ports)
        assessment = assess_activity(inputs=inputs, config=self._activity)
        if key is not None:
            active_at = (
                last_active_at(inputs=inputs, config=self._activity)
                if assessment.state is ActivityState.ACTIVE
                else None
            )
            self._last_active.observe(key=key, assessment=assessment, active_at=active_at)
        return assessment

    def _inputs_for(
        self,
        *,
        key: EntityKey | None,
        category: Category | None,
        now: datetime,
        ports: frozenset[int],
    ) -> ActivityInputs:
        created = (
            datetime.fromtimestamp(key[1], tz=UTC)
            if isinstance(key, tuple)
            else self.monitor_started_at
        )
        return ActivityInputs(
            category=category or Category.OTHER,
            history=self.history.history_for(key=key) if key is not None else (),
            now=now,
            created_at=created,
            monitor_started_at=self.monitor_started_at,
            # Last activity seen this session (or persisted at start): without it an
            # entity active an hour ago looked idle since the monitor started.
            persisted_last_active=self._last_active.last_active(key=key)
            if key is not None
            else None,
            server_ports=ports,
        )

    def _assemble(
        self,
        *,
        drafts: tuple[GroupDraft, ...],
        entities: Entities,
        verdicts: Verdicts,
        system: tuple[datetime, DockerStatus],
    ) -> Snapshot:
        if self._mem is None:
            raise RuntimeError("Memory counters are not ready")
        return assemble_snapshot(
            inputs=AssemblyInput(
                drafts=drafts,
                entities=entities,
                verdicts=verdicts,
                system=SystemState(
                    mem=self._mem,
                    disks=self._disks,
                    docker=system[1],
                    reclaimable_disk=self._reclaimable_disk,
                ),
                taken_at=system[0],
                monitor_started_at=self.monitor_started_at,
                user=self._user,
                thresholds=Thresholds(
                    warning_pct=self.settings.pressure_warning_pct,
                    critical_pct=self.settings.pressure_critical_pct,
                ),
            )
        )
