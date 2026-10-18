"""A provider of several fake engines, each with its own client. Nothing touches Docker."""

from typing import Any

from wimm.collectors.docker_engines import Engine, EngineView
from wimm.model.actions import EngineIdentity


def engine_at(*, path: str, client: Any) -> Engine:
    identity = EngineIdentity(path=path, st_ino=1, st_dev=1)
    return Engine(client=client, engine_id=path, identity=identity)


class FakeProvider:
    """`EngineProvider` over a fixed list of engines; counts the refreshes."""

    def __init__(self, *, engines: tuple[Engine, ...]) -> None:
        self._view = EngineView(engines=engines, notices=())
        self.refreshes = 0

    def refresh(self) -> EngineView:
        self.refreshes += 1
        return self._view

    def discard(self, *, engine: Engine) -> None:
        return None
