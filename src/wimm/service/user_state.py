from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Any, Protocol

from wimm.core.assemble import UserState
from wimm.model.enums import GroupId
from wimm.service.sampler import wall_clock
from wimm.service.state_store import PersistedState

SNOOZE_GROUP_S = 24 * 3600


class StateUpdater(Protocol):
    def update(self, *, changes: Mapping[str, Any]) -> None: ...


def _require_positive(*, duration_s: float) -> None:
    if duration_s <= 0:
        raise ValueError(f"duration_s must be positive, got {duration_s!r}")


def _require_group(*, group_id: GroupId) -> None:
    if not group_id:
        raise ValueError("group_id must not be empty")


class UserStateKeeper:
    """The user's choices in one place: group snoozes, ignored groups, global mute (RF-27).

    Main loop only. Snoozes and ignores are persisted through the state saver; the global
    mute is a session choice and is not. ``user_state`` returns an immutable value that
    the service hands to the sampler, which runs on the worker.
    """

    def __init__(
        self, *, state: PersistedState, clock: Callable[[], datetime] = wall_clock
    ) -> None:
        self._clock = clock
        self._saver: StateUpdater | None = None
        self._snoozes: Mapping[GroupId, datetime] = self._live(snoozes=state.snoozes)
        self._ignored: frozenset[GroupId] = state.ignored
        self._muted_until: datetime | None = None

    def attach_saver(self, *, saver: StateUpdater) -> None:
        self._saver = saver

    @property
    def muted_until(self) -> datetime | None:
        """Wall-clock end of the global mute, or None when not muted or already elapsed."""
        if self._muted_until is not None and self._clock() >= self._muted_until:
            self._muted_until = None
        return self._muted_until

    def user_state(self) -> UserState:
        return UserState(ignored=self._ignored, snoozed_until=self._live(snoozes=self._snoozes))

    def snooze(self, *, group_id: GroupId, duration_s: float) -> None:
        """Silence ``group_id`` for ``duration_s`` seconds from now."""
        _require_group(group_id=group_id)
        _require_positive(duration_s=duration_s)
        live = dict(self._live(snoozes=self._snoozes))
        live[group_id] = self._clock() + timedelta(seconds=duration_s)
        self._snoozes = MappingProxyType(live)
        self._persist(changes={"snoozes": self._snoozes})

    def set_ignored(self, *, group_id: GroupId, ignored: bool) -> None:
        _require_group(group_id=group_id)
        self._ignored = self._ignored | {group_id} if ignored else self._ignored - {group_id}
        self._persist(changes={"ignored": self._ignored})

    def snooze_all(self, *, duration_s: float) -> None:
        """Silence every notification for ``duration_s`` seconds from now."""
        _require_positive(duration_s=duration_s)
        self._muted_until = self._clock() + timedelta(seconds=duration_s)

    def _live(self, *, snoozes: Mapping[GroupId, datetime]) -> Mapping[GroupId, datetime]:
        now = self._clock()
        return MappingProxyType({g: until for g, until in snoozes.items() if until > now})

    def _persist(self, *, changes: Mapping[str, Any]) -> None:
        if self._saver is not None:
            self._saver.update(changes=changes)
