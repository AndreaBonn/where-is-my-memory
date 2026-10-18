"""The label guide follows a language switched while the tray item is running (RF-40)."""

from pathlib import Path

import pytest

from tests.tray.conftest import Bus
from tests.tray.test_status_notifier import get, make_item
from wimm import i18n


@pytest.mark.dbus
def test_label_guide_follows_a_language_switch_at_runtime(bus: Bus, english_catalog: Path) -> None:
    item = make_item(bus, [])
    try:
        assert get(bus, "XAyatanaLabelGuide") == "88,8 GB da liberare"

        i18n.set_language(language=i18n.ENGLISH)

        assert get(bus, "XAyatanaLabelGuide") == "88.8 GB to free up"
    finally:
        item.close()
