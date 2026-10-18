import pytest

from wimm.core.notify_types import NotificationIntent
from wimm.model.enums import GroupId
from wimm.service.notifier import build_spec


@pytest.mark.usefixtures("english")
def test_notification_buttons_read_in_english() -> None:
    intent = NotificationIntent(id="idle-x", title="t", body="b", group_id=GroupId("x"))
    assert [button.label for button in build_spec(intent=intent).buttons] == [
        "See and decide",
        "Not now (24 h)",
    ]
