from dataclasses import dataclass, fields
from datetime import datetime
from typing import get_origin


def require_aware(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError(f"{field} must be a timezone-aware datetime")
    return value


def require_bytes(value: int, field: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field} must be a nonnegative integer byte count")


def require_immutable(value: object, field: str) -> None:
    if isinstance(value, list | dict | set | bytearray):
        raise ValueError(f"{field} must be immutable")
    if isinstance(value, tuple | frozenset):
        for item in value:
            require_immutable(value=item, field=field)


@dataclass(frozen=True, slots=True)
class ImmutableModel:
    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            collection = get_origin(item.type)
            if collection in (tuple, frozenset) and type(value) is not collection:
                raise ValueError(f"{item.name} must be a {collection.__name__}")
            require_immutable(value=value, field=item.name)
            if isinstance(value, datetime):
                require_aware(value=value, field=item.name)


MAX_PORT = 65535


def require_nonnegative(value: int, field: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field} must be a nonnegative integer")


def require_ports(values: tuple[int, ...], field: str) -> None:
    for value in values:
        require_nonnegative(value=value, field=field)
        if value > MAX_PORT:
            raise ValueError(f"{field} must be in 0..{MAX_PORT}")
