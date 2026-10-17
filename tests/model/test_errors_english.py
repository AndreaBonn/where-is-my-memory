import pytest

from wimm.i18n import _
from wimm.model.errors import InvalidRequest, ProtectedTarget, WimmError


@pytest.mark.usefixtures("english")
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (WimmError, "The operation failed"),
        (ProtectedTarget, "This item is protected and cannot be changed"),
        (InvalidRequest, "The request is not valid"),
    ],
)
def test_user_message_is_translated_where_it_is_shown(
    error: type[WimmError], expected: str
) -> None:
    assert _(error.user_message) == expected


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (WimmError, "L'operazione non è riuscita"),
        (ProtectedTarget, "L'elemento è protetto e non può essere modificato"),
        (InvalidRequest, "La richiesta non è valida"),
    ],
)
def test_user_message_stays_italian_by_default(error: type[WimmError], expected: str) -> None:
    assert _(error.user_message) == expected
    assert error.user_message == expected


@pytest.mark.usefixtures("english")
def test_internal_message_is_never_translated() -> None:
    assert str(InvalidRequest()) == "Action request is invalid"
