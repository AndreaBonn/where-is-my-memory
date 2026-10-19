import pytest

from wimm.model.cache_items import CacheRest
from wimm.model.validation import ImmutableModel, require_text


def test_require_text_accepts_text() -> None:
    require_text(value="x", field="name")


@pytest.mark.parametrize("value", ["", "  ", "\t\n", None, 3])
def test_require_text_rejects_blank_or_non_text(value: object) -> None:
    with pytest.raises(ValueError, match="name must not be blank"):
        require_text(value=value, field="name")  # type: ignore[arg-type]


def test_cache_rest_is_an_immutable_model_that_still_validates_bytes() -> None:
    assert isinstance(CacheRest(), ImmutableModel)
    with pytest.raises(ValueError, match="shared"):
        CacheRest(shared=-1)
