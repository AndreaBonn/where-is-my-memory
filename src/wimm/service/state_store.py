import json
import logging
import math
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from types import MappingProxyType
from typing import Any

from wimm.core.notify_rules import Episode, NotificationState
from wimm.model.enums import GroupId
from wimm.paths import UserPaths, ensure_private_dir, write_private_atomic
from wimm.service.history import EntityKey

LOGGER = logging.getLogger(__name__)
STATE_FILE = "state.json"
STATE_VERSION = 1
_EMPTY: Mapping[Any, Any] = MappingProxyType({})


@dataclass(frozen=True)
class PersistedState:
    """What survives a restart (spec 11): activity instants, snoozes, ignores, notifications."""

    last_active: Mapping[EntityKey, datetime] = field(default_factory=lambda: _EMPTY)
    snoozes: Mapping[GroupId, datetime] = field(default_factory=lambda: _EMPTY)
    ignored: frozenset[GroupId] = frozenset()
    notifications: NotificationState = field(default_factory=NotificationState)


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Expected an ISO timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Timestamp without timezone")
    return parsed


def _parse_text(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("Expected a nonempty string")
    return value


def _parse_key(raw: Mapping[str, Any]) -> EntityKey:
    if "container" in raw:
        return _parse_text(raw["container"])
    pid, create_time = raw["process"]
    valid = type(pid) is int and type(create_time) in (int, float) and math.isfinite(create_time)
    if not valid:
        raise ValueError("Invalid process identity")
    return (pid, float(create_time))


def _entries[T](raw: object, *, section: str, parse: Callable[[Any], T]) -> list[T]:
    """Parse each element on its own; an invalid one is dropped with a WARNING."""
    if not isinstance(raw, list):
        LOGGER.warning("state.json: section %r is not a list, ignored", section)
        return []
    parsed: list[T] = []
    for item in raw:
        try:
            parsed.append(parse(item))
        except (ValueError, TypeError, KeyError, AttributeError):
            LOGGER.warning("state.json: invalid entry dropped from %r", section)
    return parsed


def _pressure(raw: object) -> dict[str, datetime]:
    if not isinstance(raw, dict):
        LOGGER.warning("state.json: section 'pressure_sent' is not an object, ignored")
        return {}
    pairs = _entries(list(raw.items()), section="pressure_sent", parse=_parse_pressure_pair)
    return dict(pairs)


def _parse_pressure_pair(pair: tuple[object, object]) -> tuple[str, datetime]:
    return _parse_text(pair[0]), _parse_time(pair[1])


def _parse_snooze(item: Mapping[str, Any]) -> tuple[GroupId, datetime]:
    return GroupId(_parse_text(item["group_id"])), _parse_time(item["until"])


def _parse_episode(item: Mapping[str, Any]) -> Episode:
    return GroupId(_parse_text(item["group_id"])), _parse_time(item["since"])


def _parse_last_active(item: Mapping[str, Any]) -> tuple[EntityKey, datetime]:
    return _parse_key(item), _parse_time(item["at"])


def _decode(raw: Mapping[str, Any], *, now: datetime) -> PersistedState:
    snoozes = _entries(raw.get("snoozes", []), section="snoozes", parse=_parse_snooze)
    notifications = NotificationState(
        episodes=frozenset(
            _entries(raw.get("episodes", []), section="episodes", parse=_parse_episode)
        ),
        pressure_sent=MappingProxyType(_pressure(raw.get("pressure_sent", {}))),
        sent_at=tuple(_entries(raw.get("sent_at", []), section="sent_at", parse=_parse_time)),
    )
    return PersistedState(
        last_active=MappingProxyType(
            dict(
                _entries(
                    raw.get("last_active", []), section="last_active", parse=_parse_last_active
                )
            )
        ),
        snoozes=MappingProxyType({group: until for group, until in snoozes if until > now}),
        ignored=frozenset(
            GroupId(v)
            for v in _entries(raw.get("ignored", []), section="ignored", parse=_parse_text)
        ),
        notifications=notifications,
    )


def load_state(*, paths: UserPaths, now: datetime) -> PersistedState:
    """Read ``state.json``; anything unreadable yields an empty state, never an exception.

    A missing file is the normal first run. A truncated or malformed file is logged as a
    WARNING and ignored. Invalid entries are dropped one by one and expired snoozes are
    discarded.
    """
    target = paths.state_dir / STATE_FILE
    try:
        raw = json.loads(target.read_bytes())
    except FileNotFoundError:
        return PersistedState()
    except (OSError, ValueError, RecursionError) as error:
        LOGGER.warning("Cannot read %s, starting with an empty state: %s", target, error)
        return PersistedState()
    if not isinstance(raw, dict) or raw.get("version") != STATE_VERSION:
        LOGGER.warning("Unexpected content in %s, starting with an empty state", target)
        return PersistedState()
    return _decode(raw, now=now)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _encode_key(key: EntityKey, at: datetime) -> dict[str, Any]:
    identity = {"container": key} if isinstance(key, str) else {"process": [key[0], key[1]]}
    return {**identity, "at": _iso(at)}


def _encode(state: PersistedState) -> dict[str, Any]:
    notified = state.notifications
    return {
        "version": STATE_VERSION,
        "last_active": [_encode_key(key, at) for key, at in state.last_active.items()],
        "snoozes": [{"group_id": g, "until": _iso(u)} for g, u in state.snoozes.items()],
        "ignored": sorted(state.ignored),
        "episodes": [{"group_id": g, "since": _iso(s)} for g, s in sorted(notified.episodes)],
        "pressure_sent": {kind: _iso(at) for kind, at in notified.pressure_sent.items()},
        "sent_at": [_iso(at) for at in notified.sent_at],
    }


def save_state(*, paths: UserPaths, state: PersistedState) -> None:
    """Write ``state.json`` atomically with private permissions.

    Raises
    ------
    OSError
        When the file cannot be written; the previous file is left untouched.
    """
    ensure_private_dir(path=paths.state_dir)
    data = json.dumps(_encode(state), indent=2, sort_keys=True).encode()
    write_private_atomic(path=paths.state_dir / STATE_FILE, data=data)


class StateSaver:
    """Periodic and final persistence of the state, safe to call from any thread.

    ``last_active`` is read at every save, so the file always carries the sampler's
    latest instants. The other sections are the ones loaded at startup until the
    services that own them hand updates in through ``update``.
    """

    def __init__(
        self,
        *,
        paths: UserPaths,
        state: PersistedState,
        last_active: Callable[[], Mapping[EntityKey, datetime]],
    ) -> None:
        self._paths = paths
        self._state = state
        self._last_active = last_active
        self._lock = threading.Lock()
        self._closed = False

    def update(self, *, changes: Mapping[str, Any]) -> None:
        """Replace sections of the kept state, for example ``ignored`` or ``snoozes``."""
        with self._lock:
            self._state = replace(self._state, **changes)

    def save(self) -> None:
        """Write the state unless closed; a failure is logged, the app keeps running."""
        with self._lock:
            if not self._closed:
                self._write()

    def close(self) -> None:
        """Write the final state and refuse every later save."""
        with self._lock:
            if not self._closed:
                self._write()
                self._closed = True

    def _write(self) -> None:
        try:
            live = MappingProxyType(dict(self._last_active()))
            save_state(paths=self._paths, state=replace(self._state, last_active=live))
        except Exception:
            LOGGER.exception("Cannot save %s", STATE_FILE)
