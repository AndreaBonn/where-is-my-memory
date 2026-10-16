from collections import deque
from collections.abc import Mapping

from wimm.core.activity import EntitySample

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
