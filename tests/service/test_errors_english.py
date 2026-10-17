import pytest

from wimm.i18n import _
from wimm.model.errors import WimmError
from wimm.service.errors import (
    ConfirmationMismatch,
    ControlFailed,
    DockerUnavailable,
    PlanExpired,
    PlanNotFound,
    TargetChanged,
    TargetGone,
)


@pytest.mark.usefixtures("english")
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (PlanExpired, "The plan has expired. Ask for a new preview"),
        (PlanNotFound, "The requested plan is not available"),
        (TargetChanged, "The item has changed. Ask for a new preview"),
        (ConfirmationMismatch, "The confirmation text does not match"),
        (DockerUnavailable, "Docker is not available"),
        (ControlFailed, "The operation failed"),
        (TargetGone, "The item no longer exists"),
    ],
)
def test_service_user_message_is_translated_where_it_is_shown(
    error: type[WimmError], expected: str
) -> None:
    assert _(error.user_message) == expected
