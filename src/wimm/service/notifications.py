import logging
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Any, Protocol

from wimm.config import Config
from wimm.core.notify_rules import NotificationState, NotifyRequest, evaluate_notifications
from wimm.model.enums import GroupId
from wimm.model.snapshot import Snapshot
from wimm.service.notifier import NotificationSink, Notifier
from wimm.service.sampler import wall_clock
from wimm.service.state_store import PersistedState

LOGGER = logging.getLogger(__name__)
SNOOZE_DURATION = timedelta(hours=24)
SNAPSHOT_SIGNAL = "snapshot-updated"


class NotificationSource(Protocol):
    """The slice of ``AppService`` the coordinator reads."""

    @property
    def notifications_muted_until(self) -> datetime | None: ...

    def snapshot(self) -> Snapshot | None: ...

    def config(self) -> Config: ...

    def connect(self, detailed_signal: str, handler: Callable[..., Any]) -> int: ...


class StateUpdater(Protocol):
    def update(self, *, changes: Mapping[str, Any]) -> None: ...


class NotificationCoordinator:
    """Runs the notification rules on every new snapshot; main loop only, no blocking I/O.

    Keeps the idle episodes already notified and the per-group snoozes. Both go to the
    state saver, which writes them on its worker, so they survive a restart. A snooze
    lives here and not in the sampler: the sampler runs on the worker, and the rules only
    need ``Group.snoozed_until``, which this class fills in before evaluating.
    """

    def __init__(
        self,
        *,
        notifier: Notifier,
        saver: StateUpdater | None,
        state: PersistedState,
        clock: Callable[[], datetime] = wall_clock,
    ) -> None:
        self._notifier = notifier
        self._saver = saver
        self._clock = clock
        self._notified: NotificationState = state.notifications
        self._snoozes: Mapping[GroupId, datetime] = state.snoozes

    def attach(self, *, source: NotificationSource) -> None:
        source.connect(SNAPSHOT_SIGNAL, self._on_snapshot)

    def snooze_group(self, *, group_id: GroupId) -> None:
        """Silence ``group_id`` for 24 h from now (RF-27); an empty target is ignored."""
        if not group_id:
            return
        now = self._clock()
        live = {g: until for g, until in self._snoozes.items() if until > now}
        live[group_id] = now + SNOOZE_DURATION
        self._snoozes = MappingProxyType(live)
        self._persist(changes={"snoozes": self._snoozes})

    def _on_snapshot(self, source: NotificationSource) -> None:
        snapshot = source.snapshot()
        if snapshot is None:
            return
        try:
            self._evaluate(source=source, snapshot=snapshot)
        except Exception:
            # Notifications are secondary: a bus failure must not stop the sampling loop.
            LOGGER.exception("Cannot evaluate or send notifications")

    def _evaluate(self, *, source: NotificationSource, snapshot: Snapshot) -> None:
        now = self._clock()
        result = evaluate_notifications(
            request=NotifyRequest(
                snapshot=self._with_snoozes(snapshot=snapshot, now=now),
                config=source.config(),
                state=self._notified,
                now=now,
                muted_until=source.notifications_muted_until,
            )
        )
        self._notifier.notify(intents=result.intents)
        if result.state != self._notified:
            self._notified = result.state
            self._persist(changes={"notifications": result.state})

    def _with_snoozes(self, *, snapshot: Snapshot, now: datetime) -> Snapshot:
        active = {g: until for g, until in self._snoozes.items() if until > now}
        if not active:
            return snapshot
        groups = tuple(
            replace(group, snoozed_until=active[group.id]) if group.id in active else group
            for group in snapshot.groups
        )
        return replace(snapshot, groups=groups)

    def _persist(self, *, changes: Mapping[str, Any]) -> None:
        if self._saver is not None:
            self._saver.update(changes=changes)


def attach_notifications(
    *,
    service: NotificationSource,
    sink: NotificationSink,
    saver: StateUpdater | None,
    state: PersistedState,
) -> NotificationCoordinator:
    """Build the coordinator and subscribe it to ``service``; call before ``service.start``."""
    coordinator = NotificationCoordinator(notifier=Notifier(sink=sink), saver=saver, state=state)
    coordinator.attach(source=service)
    return coordinator
