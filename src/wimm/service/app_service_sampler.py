"""What the service needs from the sampler that builds each snapshot."""

from typing import Protocol

from wimm.config import Config
from wimm.core.assemble import UserState
from wimm.model.snapshot import Snapshot


class CycleSampler(Protocol):
    def apply_config(self, *, config: Config) -> None: ...

    def apply_user_state(self, *, user: UserState) -> None: ...

    def apply_reclaimable_disk(self, *, reclaimable_disk: int) -> None: ...

    def run_cycle(self) -> Snapshot: ...
