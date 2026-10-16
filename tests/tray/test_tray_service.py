from functools import partial

import pytest

from tests.service.test_app_service import FakeSampler, spin_until
from tests.tray.conftest import Bus
from wimm.config import Config
from wimm.service.app_service import AppService
from wimm.tray.menu_model import ICON_NORMAL, ICON_WARNING
from wimm.tray.status_notifier import SNI_IFACE, SNI_OBJECT_PATH
from wimm.tray.tray import Tray


def reached(service: AppService, failures: int) -> bool:
    return service.consecutive_failures == failures


def ignore(_group_id: str | None) -> None:
    return None


@pytest.mark.dbus
def test_tray_follows_a_real_service_through_failures_and_recovery(bus: Bus) -> None:
    sampler = FakeSampler()
    sampler.proceed.set()
    sampler.fail = True
    service = AppService(sampler=sampler, config=Config())
    tray = Tray(connection=bus.server, service=service, on_open=ignore, on_quit=lambda: None)

    def icon() -> object:
        return bus.get(path=SNI_OBJECT_PATH, interface=SNI_IFACE, name="IconName")

    try:
        assert icon() == ICON_NORMAL
        service.start()
        spin_until(predicate=lambda: service.consecutive_failures == 1)
        for expected in (2, 3, 4):
            service.request_cycle()
            spin_until(predicate=partial(reached, service, expected))
        assert service.consecutive_failures == 4
        assert icon() == ICON_WARNING
        sampler.fail = False
        service.request_cycle()
        spin_until(predicate=lambda: service.snapshot() is not None)
        assert service.consecutive_failures == 0
        assert bus.get(path=SNI_OBJECT_PATH, interface=SNI_IFACE, name="XAyatanaLabel") == ""
    finally:
        tray.close()
        service.stop()
