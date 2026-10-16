from typing import Any, cast


def invalid_model_value(value: object) -> Any:
    """Pass deliberately invalid runtime input through static model contracts."""
    return cast(Any, value)
