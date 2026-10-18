"""What the service needs from the sampler that builds each snapshot."""

import logging
from collections.abc import Mapping
from typing import Protocol

from wimm.config import Config
from wimm.core.assemble import UserState
from wimm.model.snapshot import Snapshot

LOGGER = logging.getLogger(__name__)


class ConfigTarget(Protocol):
    def apply_config(self, *, config: Config) -> None: ...


class CycleSampler(ConfigTarget, Protocol):
    def apply_user_state(self, *, user: UserState) -> None: ...

    def apply_reclaimable_disk(self, *, reclaimable_disk: int) -> None: ...

    def run_cycle(self) -> Snapshot: ...


def adopt_config(*, config: Config, parts: Mapping[str, ConfigTarget]) -> None:
    """Apply ``config`` to each named part on its own: one failure never stops the next.

    A failing sampler must not leave the executor without the protected names and roots
    the user just saved (SPECIFICHE 8.2).
    """
    for name, part in parts.items():
        try:
            part.apply_config(config=config)
        except Exception:
            LOGGER.exception("Cannot apply the new configuration to the %s", name)
