import pytest
from gi.repository import GObject

from tests.tray.conftest import Bus
from tests.tray.test_tray import FakeService
from wimm.tray.tray import Tray


def build(bus: Bus, service: FakeService) -> Tray:
    return Tray(
        connection=bus.server,
        service=service,
        on_open=lambda _group_id: None,
        on_quit=lambda: None,
    )


def has_handlers(service: FakeService) -> bool:
    signal_id = GObject.signal_lookup("snapshot-updated", FakeService.__gtype__)
    return GObject.signal_has_handler_pending(service, signal_id, 0, True)


@pytest.mark.dbus
def test_a_tray_that_fails_to_build_releases_its_objects_and_handlers(bus: Bus) -> None:
    service = FakeService()
    service.broken = True
    with pytest.raises(RuntimeError, match="boom"):
        build(bus=bus, service=service)
    assert not has_handlers(service=service)
    # The D-Bus paths are free again: a second export would fail if they were still taken.
    service.broken = False
    tray = build(bus=bus, service=service)
    try:
        assert has_handlers(service=service)  # positive pair for the assertion above
    finally:
        tray.close()
