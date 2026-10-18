import os
from typing import Any, cast

# CPython 3.12 reports a new attribute on a frozen slotted dataclass through super();
# later releases raise FrozenInstanceError("cannot assign to field").
SLOTTED_FROZEN_ERROR = "super|cannot assign"


def invalid_model_value(value: object) -> Any:
    """Pass deliberately invalid runtime input through static model contracts."""
    return cast(Any, value)


class FailingHandle:
    """A file object whose read fails the way a dying disk does."""

    def __init__(self, descriptor: int) -> None:
        self._descriptor = descriptor

    def __enter__(self) -> "FailingHandle":
        return self

    def __exit__(self, *exc: object) -> None:
        os.close(self._descriptor)

    def fileno(self) -> int:
        return self._descriptor

    def read(self, size: int) -> bytes:
        raise OSError(5, "Input/output error")
