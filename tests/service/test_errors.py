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
    "error_type,code,user_message",
    [
        (PlanExpired, "PLAN_EXPIRED", "Il piano è scaduto. Richiedi una nuova anteprima"),
        (PlanNotFound, "PLAN_NOT_FOUND", "Il piano richiesto non è disponibile"),
        (
            TargetChanged,
            "TARGET_CHANGED",
            "L'elemento è cambiato. Richiedi una nuova anteprima",
        ),
        (ConfirmationMismatch, "CONFIRMATION_MISMATCH", "Il testo di conferma non corrisponde"),
        (
            ProtectedTarget,
            "PROTECTED_TARGET",
            "L'elemento è protetto e non può essere modificato",
        ),
        (DockerUnavailable, "DOCKER_UNAVAILABLE", "Docker non è disponibile"),
        (InvalidRequest, "INVALID_REQUEST", "La richiesta non è valida"),
    ],
)
def test_named_errors_have_internal_and_user_messages(
    error_type: type[WimmError], code: str, user_message: str
) -> None:
    error = error_type()
    assert isinstance(error, WimmError)
    assert error.code == code
    assert str(error) == error.message
    assert error.user_message == user_message
    assert error.user_message != str(error)
    custom = error_type(message="Specific internal detail")
    assert str(custom) == "Specific internal detail"
    assert custom.user_message == error.user_message
