"""Decoding primitives of the JSON wire forms: strict types, unknown and missing fields rejected."""

import math
from collections.abc import Callable
from datetime import datetime
from enum import Enum
from typing import Any

from wimm import model as m

Decoder = Callable[[Any, str], Any]
Schema = dict[str, Decoder]


class SnapshotFormatError(ValueError):
    pass


def primitive(expected: type) -> Decoder:
    def decode(value: Any, path: str) -> Any:
        if type(value) is not expected:
            raise SnapshotFormatError(f"{path}: expected {expected.__name__}")
        return value

    return decode


def byte_count(value: Any, path: str) -> int:
    m.validation.require_bytes(value=value, field=path)
    return int(value)


def float_value(value: Any, path: str) -> float:
    if type(value) not in (int, float):
        raise SnapshotFormatError(f"{path}: expected a finite number")
    try:
        number = float(value)
    except OverflowError as error:
        raise SnapshotFormatError(f"{path}: number exceeds float range") from error
    if not math.isfinite(number):
        raise SnapshotFormatError(f"{path}: expected a finite number")
    return number


def timestamp(value: Any, path: str) -> datetime:
    text = primitive(expected=str)(value, path)
    try:
        return m.require_aware(value=datetime.fromisoformat(text), field=path)
    except ValueError as error:
        raise SnapshotFormatError(f"{path}: {error}") from error


def enumeration(enum: type[Enum]) -> Decoder:
    def decode(value: Any, path: str) -> Enum:
        text = primitive(expected=str)(value, path)
        if enum is m.Risk and text not in {risk.name.lower() for risk in m.Risk}:
            raise SnapshotFormatError(f"{path}: invalid Risk {text!r}")
        try:
            return enum[text.upper()] if enum is m.Risk else enum(text)
        except (ValueError, KeyError) as error:
            raise SnapshotFormatError(f"{path}: invalid {enum.__name__} {text!r}") from error

    return decode


def nullable(decoder: Decoder) -> Decoder:
    def decode(value: Any, path: str) -> Any:
        return None if value is None else decoder(value, path)

    return decode


def sequence(decoder: Decoder) -> Decoder:
    def decode(value: Any, path: str) -> tuple[Any, ...]:
        items = primitive(expected=list)(value, path)
        return tuple(decoder(item, f"{path}[{index}]") for index, item in enumerate(items))

    return decode


def fields(value: Any, schema: Schema, path: str) -> dict[str, Any]:
    data = primitive(expected=dict)(value, path)
    missing, unknown = schema.keys() - data.keys(), data.keys() - schema.keys()
    if missing or unknown:
        names = ", ".join(sorted(missing | unknown))
        raise SnapshotFormatError(f"{path}: missing or unknown fields: {names}")
    return {name: decoder(data[name], f"{path}.{name}") for name, decoder in schema.items()}


def literal(expected: str | int) -> Decoder:
    def decode(value: Any, path: str) -> Any:
        if type(value) is not type(expected) or value != expected:
            raise SnapshotFormatError(f"{path}: expected {expected!r}")
        return value

    return decode


TEXT = primitive(expected=str)
INTEGER = primitive(expected=int)
BOOLEAN = primitive(expected=bool)
