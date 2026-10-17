import logging
from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import ClassVar, Protocol

from gi.repository import GLib, GObject

from wimm.config import Config, ConfigParseResult, save_config, update_config
from wimm.core import constants as c
from wimm.core.assemble import UserState
from wimm.core.planning import PlanningContext, plan_action
from wimm.model.actions import ActionRequest, Plan
from wimm.model.enums import PlanId
from wimm.model.snapshot import Snapshot
from wimm.paths import UserPaths
from wimm.service.actions import ActionExecutor, ActionSetup
from wimm.service.app_service_disk import DiskMixin
from wimm.service.app_service_signals import APP_SERVICE_SIGNALS
from wimm.service.app_service_user import UserStateMixin
from wimm.service.control_protocols import StepOutcome
from wimm.service.errors import ControlFailed, InvalidRequest, WimmError
from wimm.service.plan_registry import PlanRegistry
from wimm.service.reclaim import ReclaimTracker
from wimm.service.sampler import wall_clock
from wimm.service.state_store import PersistedState, StateSaver
from wimm.service.user_state import UserStateKeeper

LOGGER = logging.getLogger(__name__)
_ActionResult = tuple[tuple[StepOutcome, ...], Snapshot | None]


class CycleSampler(Protocol):
    def apply_config(self, *, config: Config) -> None: ...

    def apply_user_state(self, *, user: UserState) -> None: ...

    def apply_reclaimable_disk(self, *, reclaimable_disk: int) -> None: ...

    def run_cycle(self) -> Snapshot: ...


class AppService(UserStateMixin, DiskMixin, GObject.Object):
    __gsignals__: ClassVar = APP_SERVICE_SIGNALS

    def __init__(
        self,
        *,
        sampler: CycleSampler,
        config: Config,
        clock: Callable[[], datetime] = wall_clock,
        actions: ActionSetup | None = None,
    ) -> None:
        super().__init__()
        self._state_saver: StateSaver | None = None
        self._state_timer = 0
        self._actions = actions
        self._plans = PlanRegistry()
        self._reclaim = ReclaimTracker()
        self._cycle_cohort: frozenset[PlanId] = frozenset()
        self._last_sampled: Snapshot | None = None
        self._init_disk()
        self._clock = clock
        self._user = UserStateKeeper(state=PersistedState(), clock=clock)
        self._sampler = sampler
        self._config = config
        self._snapshot: Snapshot | None = None
        # One worker for sampling and actions: a sample never reads mid-action.
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wimm-worker")
        self._timer = 0
        self._busy = False
        self._cycle_pending = False
        self._stopped = False
        self.consecutive_failures = 0

    def snapshot(self) -> Snapshot | None:
        return self._snapshot

    def config(self) -> Config:
        return self._config

    def update_config(
        self, *, changes: Mapping[str, object], paths: UserPaths, home: Path
    ) -> ConfigParseResult:
        """Validate, persist and apply preference changes; invalid fields keep their value.

        A new sample interval reschedules the running timer. The sampler and the action
        executor adopt the new values on the worker, so never in the middle of a cycle or
        of a plan.

        Raises
        ------
        OSError
            When the file cannot be written; the running configuration is unchanged.
        """
        if self._stopped:
            # The worker is gone: saving now would change a file nothing applies.
            raise InvalidRequest("The service is stopped")
        result = update_config(config=self._config, changes=changes, home=home)
        if result.config == self._config:
            return result
        save_config(paths=paths, config=result.config)
        previous, self._config = self._config, result.config
        self._executor.submit(self._apply_config, result.config)
        # Sample right away, so a protected name added or removed shows in the window now.
        self.request_cycle()
        self._reschedule_timers(previous=previous)
        return result

    def _reschedule_timers(self, *, previous: Config) -> None:
        if self._config.sample_interval_s != previous.sample_interval_s:
            self._reschedule_timer()
        if self._config.disk_scan_interval_s != previous.disk_scan_interval_s:
            self._reschedule_disk_timer()

    def _reschedule_timer(self) -> None:
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = GLib.timeout_add_seconds(
                self._config.sample_interval_s, self.request_cycle
            )

    def start(self) -> None:
        if self._timer or self._stopped:
            return
        self._timer = GLib.timeout_add_seconds(self._config.sample_interval_s, self.request_cycle)
        if self._state_saver is not None:
            self._state_timer = GLib.timeout_add_seconds(
                c.STATE_SAVE_INTERVAL_S, self.save_state_tick
            )
        self._user_changed()
        self._start_disk()

    def attach_state_saver(self, *, saver: StateSaver) -> None:
        """Persist through ``saver`` every 5 minutes and on stop; call before ``start``."""
        self._state_saver = saver
        self._user.attach_saver(saver=saver)

    def save_state_tick(self) -> bool:
        """Periodic save, on the worker so the main loop never waits for the disk."""
        if self._state_saver is not None and not self._stopped:
            self._executor.submit(self._state_saver.save)
        return GLib.SOURCE_CONTINUE

    def request_cycle(self) -> bool:
        # A request during a running cycle is kept: that cycle predates the change.
        self._cycle_pending = self._busy and not self._stopped
        if not self._busy and not self._stopped:
            self._busy = True
            self._cycle_cohort = self._reclaim.due_ids
            future = self._executor.submit(self._sample)
            future.add_done_callback(self._completed)
        return GLib.SOURCE_CONTINUE

    def _sample(self) -> Snapshot:
        """Worker side: also remember the sample, the baseline of an action that follows."""
        self._last_sampled = self._sampler.run_cycle()
        return self._last_sampled

    def _apply_config(self, config: Config) -> None:
        """Worker side: the sampler's history is not thread-safe, so it changes only here."""
        try:
            self._sampler.apply_config(config=config)
            if self._actions is not None:
                self._actions.executor.apply_config(config=config)
        except Exception:
            LOGGER.exception("Cannot apply the new configuration")

    def _run_action(
        self, executor: ActionExecutor, plan: Plan
    ) -> tuple[tuple[StepOutcome, ...], Snapshot | None]:
        """Worker side: the baseline is the last sample taken before this action starts."""
        baseline = self._last_sampled
        return executor.execute(plan=plan), baseline

    def _submit_user_state(self, *, user: UserState) -> None:
        self._executor.submit(self._sampler.apply_user_state, user=user)

    def _completed(self, future: Future[Snapshot]) -> None:
        GLib.idle_add(self._publish, future)

    def _publish(self, future: Future[Snapshot]) -> bool:
        self._busy = False
        if self._stopped:
            return GLib.SOURCE_REMOVE
        try:
            snapshot = future.result()
        except Exception:
            self.consecutive_failures += 1
            LOGGER.exception("Sampling failed (%d consecutive cycles)", self.consecutive_failures)
            self.emit("cycle-failed")
        else:
            self._snapshot = snapshot
            self.consecutive_failures = 0
            self.emit("snapshot-updated")
            self._measure_reclaim(snapshot=snapshot)
        if self._cycle_pending:
            self.request_cycle()
        return GLib.SOURCE_REMOVE

    def plan(self, *, request: ActionRequest) -> Plan:
        """Build and register a confirmation plan from the latest snapshot (spec 8.1)."""
        setup = self._require_actions()
        if self._snapshot is None:
            raise InvalidRequest("No snapshot yet, cannot plan an action")
        context = PlanningContext(
            owner_uid=setup.owner_uid, now=self._clock, disk_report=self._disk_report
        )
        plan = plan_action(request=request, snapshot=self._snapshot, context=context)
        self._plans.add(plan=plan, now=self._clock())
        return plan

    def execute(self, *, plan_id: PlanId, typed_confirmation: str | None) -> None:
        """Validate expiry and phrase, then run the plan on the worker; returns at once.

        The plan leaves the registry before it runs, so it executes at most once. The
        result arrives on the main loop as `action-finished` or `action-rejected`.

        Raises
        ------
        PlanNotFound, PlanExpired, ConfirmationMismatch
            From the registry; a mismatch keeps the plan so the user can retype.
        """
        setup = self._require_actions()
        if self._stopped:
            raise InvalidRequest("Service is stopped")
        plan = self._plans.take(
            plan_id=plan_id, typed_confirmation=typed_confirmation, now=self._clock()
        )
        future = self._executor.submit(self._run_action, setup.executor, plan)
        future.add_done_callback(partial(self._action_completed, plan_id))

    def _require_actions(self) -> ActionSetup:
        if self._actions is None:
            raise InvalidRequest("Actions are not available")
        return self._actions

    def _action_completed(self, plan_id: PlanId, future: Future[_ActionResult]) -> None:
        GLib.idle_add(self._publish_action, plan_id, future)

    def _publish_action(self, plan_id: PlanId, future: Future[_ActionResult]) -> bool:
        if self._stopped:
            return GLib.SOURCE_REMOVE
        try:
            outcomes, before = future.result()
        except Exception as error:
            if not isinstance(error, WimmError):
                LOGGER.exception("Action %s crashed", plan_id)
            self.emit(
                "action-rejected",
                plan_id,
                error if isinstance(error, WimmError) else ControlFailed(),
            )
            return GLib.SOURCE_REMOVE
        self.emit("action-finished", plan_id, outcomes)
        if self._reclaim.watch(plan_id=plan_id, before=before):
            delay_ms = round(self._require_actions().measure_delay_s * 1000)
            GLib.timeout_add(delay_ms, self._delay_elapsed, plan_id)
        self.request_cycle()
        return GLib.SOURCE_REMOVE

    def _delay_elapsed(self, plan_id: PlanId) -> bool:
        if not self._stopped:
            self._reclaim.mark_due(plan_id=plan_id)
            self.request_cycle()
        return GLib.SOURCE_REMOVE

    def _measure_reclaim(self, *, snapshot: Snapshot) -> None:
        """Measure plans already due at submit time; later ones wait for their own sample."""
        for plan_id, delta in self._reclaim.resolve(after=snapshot, plan_ids=self._cycle_cohort):
            self.emit("reclaim-measured", plan_id, delta)
        if self._reclaim.due_ids:
            self.request_cycle()

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0
        if self._state_timer:
            GLib.source_remove(self._state_timer)
        if self._state_saver is not None:
            # Inline: the executor is not awaited, so the file is written now.
            self._state_saver.close()
        self._stop_disk()
        # Not waiting: the main loop must not freeze until a running action ends.
        self._executor.shutdown(wait=False, cancel_futures=True)
