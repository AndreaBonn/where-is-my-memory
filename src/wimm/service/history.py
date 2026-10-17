import threading
from collections import deque
from collections.abc import Mapping
from datetime import datetime, timedelta

from wimm.core.activity import EntitySample
from wimm.model.enums import ActivityState
from wimm.model.snapshot import ActivityAssessment

# Process: (pid, create_time) so a reused pid is a different entity; container: its id.
type EntityKey = tuple[int, float] | str

MAX_MISSED_CYCLES = 2


class SampleHistory:
    """Per-entity ring buffers of samples, sized ``window_s // interval_s + 1``.

    Not thread-safe by design: only the sampler worker calls it, so there is no lock.
    An entity absent for more than ``MAX_MISSED_CYCLES`` consecutive cycles is dropped.
    """

    def __init__(self, *, window_s: int, interval_s: int) -> None:
        self._maxlen = window_s // interval_s + 1
        self._samples: dict[EntityKey, deque[EntitySample]] = {}
        self._missed: dict[EntityKey, int] = {}

    def resize(self, *, window_s: int, interval_s: int) -> None:
        """Adopt new ring dimensions, keeping the latest samples that still fit."""
        maxlen = window_s // interval_s + 1
        if maxlen == self._maxlen:
            return
        self._maxlen = maxlen
        self._samples = {key: deque(ring, maxlen=maxlen) for key, ring in self._samples.items()}

    def append(self, *, cycle_samples: Mapping[EntityKey, EntitySample]) -> None:
        """Record one cycle: store the new samples and age out the absent entities."""
        for key, entity_sample in cycle_samples.items():
            ring = self._samples.setdefault(key, deque(maxlen=self._maxlen))
            ring.append(entity_sample)
            self._missed[key] = 0
        for key in [k for k in self._samples if k not in cycle_samples]:
            self._missed[key] += 1
            if self._missed[key] > MAX_MISSED_CYCLES:
                del self._samples[key]
                del self._missed[key]

    def history_for(self, *, key: EntityKey) -> tuple[EntitySample, ...]:
        """Samples of ``key``, oldest first; empty if the entity is unknown."""
        return tuple(self._samples.get(key, ()))


class LastActiveTracker:
    """Last instant each entity was seen active, seeded from the persisted state (RF-12).

    ``observe`` runs on the sampler worker, ``export`` on any thread: a lock guards both.
    """

    def __init__(self, *, persisted: Mapping[EntityKey, datetime]) -> None:
        self._last_active = dict(persisted)
        self._previous: set[EntityKey] = set()
        self._current: set[EntityKey] = set()
        self._lock = threading.Lock()

    def begin_cycle(self) -> None:
        """Start a cycle: seen means observed in this cycle or in the previous complete one.

        The previous cycle stays counted so an export from another thread, in the middle of
        a cycle, does not forget an entity that is not yet re-observed.
        """
        with self._lock:
            self._previous, self._current = self._current, set()

    def observe(
        self, *, key: EntityKey, assessment: ActivityAssessment, active_at: datetime | None
    ) -> None:
        """Active: the end of the latest active step. Idle: keep the earlier instant, else
        the assessed ``since``."""
        with self._lock:
            self._current.add(key)
            if assessment.state is ActivityState.ACTIVE and active_at is not None:
                self._last_active[key] = active_at
            elif assessment.state is ActivityState.IDLE and assessment.since is not None:
                self._last_active.setdefault(key, assessment.since)

    def last_active(self, *, key: EntityKey) -> datetime | None:
        """Last instant seen active this session, else the persisted one, else None."""
        with self._lock:
            return self._last_active.get(key)

    def export(self, *, now: datetime, retention_s: int) -> Mapping[EntityKey, datetime]:
        """Copy to persist; entities absent from the last cycle expire after ``retention_s``."""
        oldest = now - timedelta(seconds=retention_s)
        with self._lock:
            return {
                key: at
                for key, at in self._last_active.items()
                if key in self._current or key in self._previous or at >= oldest
            }
