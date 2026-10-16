from dataclasses import dataclass

import pytest

from tests.helpers import invalid_model_value
from wimm.model.validation import ImmutableModel


@dataclass(frozen=True, slots=True)
class OptionalCollections(ImmutableModel):
    names: frozenset[str] | None = None
    ports: tuple[int, ...] | None = None


def test_optional_collection_accepts_none_and_the_declared_type() -> None:
    assert OptionalCollections().names is None
    assert OptionalCollections(names=frozenset({"a"}), ports=(1, 2)).ports == (1, 2)


@pytest.mark.parametrize(
    ("field", "value"),
    [("names", ("a",)), ("ports", frozenset({1}))],
)
def test_optional_collection_rejects_other_immutable_collections(field: str, value: object) -> None:
    with pytest.raises(ValueError, match=field):
        OptionalCollections(**{field: invalid_model_value(value)})
