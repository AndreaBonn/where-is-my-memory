import logging
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, Protocol

from wimm.config import Config
from wimm.core.notify_rules import NotificationState, NotifyRequest, evaluate_notifications
from wimm.model.snapshot import Snapshot
from wimm.service.notifier import NotificationSink, Notifier
from wimm.service.sampler import wall_clock
from wimm.service.state_store import PersistedState

LOGGER = logging.getLogger(__name__)
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

    Keeps the idle episodes already notified, which go to the state saver so they survive a
    restart. Snoozes and ignores are not its business: the rules read ``Group.snoozed_until``
    and ``Group.ignored`` from the snapshot, filled in by the user state (``user_state.py``).
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

    def attach(self, *, source: NotificationSource) -> None:
        source.connect(SNAPSHOT_SIGNAL, self._on_snapshot)

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
                snapshot=snapshot,
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
