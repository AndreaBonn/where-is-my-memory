import pytest

from wimm.service.errors import (
    ConfirmationMismatch,
    DockerUnavailable,
    InvalidRequest,
    PlanExpired,
    PlanNotFound,
    ProtectedTarget,
    TargetChanged,
    WimmError,
)


@pytest.mark.parametrize(
    "error_type,code",
    [
        (PlanExpired, "PLAN_EXPIRED"),
        (PlanNotFound, "PLAN_NOT_FOUND"),
        (TargetChanged, "TARGET_CHANGED"),
        (ConfirmationMismatch, "CONFIRMATION_MISMATCH"),
        (ProtectedTarget, "PROTECTED_TARGET"),
        (DockerUnavailable, "DOCKER_UNAVAILABLE"),
        (InvalidRequest, "INVALID_REQUEST"),
    ],
)
def test_named_errors_have_internal_and_user_messages(
    error_type: type[WimmError], code: str
) -> None:
    error = error_type()
    assert isinstance(error, WimmError)
    assert error.code == code
    assert str(error) == error.message
    assert error.user_message
    assert error.user_message != str(error)
    custom = error_type(message="Specific internal detail")
    assert str(custom) == "Specific internal detail"
    assert custom.user_message == error.user_message
