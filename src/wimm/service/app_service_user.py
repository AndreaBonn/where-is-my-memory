"""The user's choices on AppService: group snoozes, ignored groups, global mute (RF-27)."""

from collections.abc import Callable
from datetime import datetime
from typing import Any

from wimm.core.assemble import UserState
from wimm.model.enums import GroupId
from wimm.service.errors import InvalidRequest
from wimm.service.state_store import PersistedState
from wimm.service.user_state import UserStateKeeper


class UserStateMixin:
    """Main loop side of the user state; the sampler gets each change on the worker.

    Mixed into ``AppService``, which provides the attributes declared here.
    """

    _user: UserStateKeeper
    _stopped: bool
    _clock: Callable[[], datetime]
    _state_saver: Any

    def request_cycle(self) -> bool:
        raise NotImplementedError

    def _submit_user_state(self, *, user: UserState) -> None:
        """Queue ``user`` for the sampler on the worker; provided by ``AppService``."""
        raise NotImplementedError

    @property
    def notifications_muted_until(self) -> datetime | None:
        """Wall-clock end of the global mute, or None when not muted or already elapsed."""
        return self._user.muted_until

    def snooze(self, *, group_id: GroupId, duration_s: float) -> None:
        """Silence one group's notifications; persisted, visible in the next snapshot."""
        self._user.snooze(group_id=group_id, duration_s=duration_s)
        self._user_changed()

    def set_ignored(self, *, group_id: GroupId, ignored: bool) -> None:
        """Exclude a group from notifications and from "reclaimable now", or restore it."""
        self._user.set_ignored(group_id=group_id, ignored=ignored)
        self._user_changed()

    def snooze_all(self, *, duration_s: float) -> None:
        """Silence every notification for ``duration_s`` seconds from now."""
        self._user.snooze_all(duration_s=duration_s)
        self._user_changed()

    def restore_user_state(self, *, state: PersistedState) -> None:
        """Adopt the snoozes and ignores of a previous run, before the state saver.

        Raises
        ------
        InvalidRequest
            Once a saver is attached: the new keeper would not persist anything.
        """
        if self._state_saver is not None:
            raise InvalidRequest("The user state must be restored before the state saver")
        self._user = UserStateKeeper(state=state, clock=self._clock)

    def _user_changed(self) -> None:
        """Hand the new user state to the sampler on the worker, then sample right away."""
        if not self._stopped:
            self._submit_user_state(user=self._user.user_state())
            self.request_cycle()
