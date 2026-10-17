import json
import math
from collections.abc import Callable
from datetime import datetime
from enum import Enum
from typing import Any

from . import model as m

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


def record[T](cls: type[T]) -> Callable[[Any, str], T]:
    def decode(value: Any, path: str) -> T:
        values = fields(value=value, schema=SCHEMAS[cls], path=path)
        protection = values.pop("protection", None)
        if cls in (m.ProcessMember, m.ContainerMember):
            values.pop("kind", None)
        try:
            result = cls(**values)
            if isinstance(result, m.Group) and result.protection is not protection:
                raise ValueError("protection disagrees with category")
            return result
        except ValueError as error:
            raise SnapshotFormatError(f"{path}: {error}") from error

    return decode


def literal(expected: str | int) -> Decoder:
    def decode(value: Any, path: str) -> Any:
        if type(value) is not type(expected) or value != expected:
            raise SnapshotFormatError(f"{path}: expected {expected!r}")
        return value

    return decode


def member(value: Any, path: str) -> m.Member:
    data = primitive(expected=dict)(value, path)
    kind = data.get("kind")
    if kind == "process":
        return record(cls=m.ProcessMember)(value, path)
    if kind == "container":
        return record(cls=m.ContainerMember)(value, path)
    raise SnapshotFormatError(f"{path}.kind: expected process or container")


def breakdown(value: Any, path: str) -> m.MemoryBreakdown:
    data = primitive(expected=dict)(value, path)
    schema: Schema = {name: byte_count for name in ("kernel_cache", "unattributed")}
    schema.update({name: byte_count for name in data if name in m.Category.__members__})
    values = fields(value=data, schema=schema, path=path)
    categories = tuple(
        (m.Category[name], size) for name, size in values.items() if name in m.Category.__members__
    )
    return m.MemoryBreakdown(
        categories=categories,
        kernel_cache=values["kernel_cache"],
        unattributed=values["unattributed"],
    )


TEXT = primitive(expected=str)
INTEGER = primitive(expected=int)
BOOLEAN = primitive(expected=bool)
ACTIVITY = record(cls=m.ActivityAssessment)
MEMORY = record(cls=m.MemoryUse)
ACTIONS = sequence(decoder=record(cls=m.ActionOffer))
SCHEMAS: dict[type, Schema] = {
    m.ActivityAssessment: {
        "state": enumeration(enum=m.ActivityState),
        "since": nullable(decoder=timestamp),
        "reason": TEXT,
    },
    m.MemoryUse: {"used": byte_count, "reclaimable": byte_count},
    m.ActionOffer: {"kind": enumeration(enum=m.ActionKind), "risk": enumeration(enum=m.Risk)},
    m.Mount: {"type": TEXT, "source": TEXT, "destination": TEXT},
    m.ProcessMember: {
        "kind": literal(expected="process"),
        "pid": INTEGER,
        "create_time": float_value,
        "uid": INTEGER,
        "name": TEXT,
        "cmdline": sequence(decoder=TEXT),
        "cwd": nullable(decoder=TEXT),
        "category": enumeration(enum=m.Category),
        "listen_ports": sequence(decoder=INTEGER),
        "memory": MEMORY,
        "activity": ACTIVITY,
        "actions": ACTIONS,
        "has_documents": BOOLEAN,
        "is_foreground": BOOLEAN,
    },
    m.ContainerMember: {
        "kind": literal(expected="container"),
        "id": TEXT,
        "name": TEXT,
        "image": TEXT,
        "state": TEXT,
        "memory": MEMORY,
        "mounts": sequence(decoder=record(cls=m.Mount)),
        "activity": ACTIVITY,
        "actions": ACTIONS,
    },
    m.Group: {
        "id": TEXT,
        "name": TEXT,
        "category": enumeration(enum=m.Category),
        "protection": enumeration(enum=m.Protection),
        "activity": ACTIVITY,
        "memory": MEMORY,
        "ports": sequence(decoder=INTEGER),
        "primary_action": nullable(decoder=record(cls=m.ActionOffer)),
        "ignored": BOOLEAN,
        "snoozed_until": nullable(decoder=timestamp),
        "explanation": TEXT,
        "compose_project": nullable(decoder=TEXT),
        "members": sequence(decoder=member),
    },
    m.MemorySummary: {
        "total": byte_count,
        "available": byte_count,
        "used": byte_count,
        "swap_total": byte_count,
        "swap_used": byte_count,
        "breakdown": breakdown,
    },
    m.DiskUsage: {"mount": TEXT, "total": byte_count, "used": byte_count, "free": byte_count},
    m.Reclaimable: {"ram": byte_count, "disk": byte_count},
    m.DockerStatus: {"available": BOOLEAN, "error": nullable(decoder=TEXT)},
    m.ProtectedSummaryItem: {"label": TEXT, "memory": byte_count, "reason": TEXT},
}
SNAPSHOT_SCHEMA: Schema = {
    "schema": literal(expected=m.SCHEMA_VERSION),
    "taken_at": timestamp,
    "monitor_started_at": timestamp,
    "memory": record(cls=m.MemorySummary),
    "disk": record(cls=m.DiskUsage),
    "reclaimable_now": record(cls=m.Reclaimable),
    "pressure": enumeration(enum=m.Pressure),
    "docker": record(cls=m.DockerStatus),
    "groups": sequence(decoder=record(cls=m.Group)),
    "protected_summary": sequence(decoder=record(cls=m.ProtectedSummaryItem)),
}


def encode(value: Any) -> Any:
    if isinstance(value, m.Risk):
        return value.name.lower()
    if isinstance(value, Enum):
        return value.name if isinstance(value, m.Category) else value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, tuple):
        return [encode(value=item) for item in value]
    if isinstance(value, m.MemoryBreakdown):
        return {
            **{category.name: size for category, size in value.categories},
            "kernel_cache": value.kernel_cache,
            "unattributed": value.unattributed,
        }
    if type(value) in SCHEMAS:
        data = {
            name: encode(value=getattr(value, name))
            for name in SCHEMAS[type(value)]
            if name != "kind" or isinstance(value, m.ActionOffer)
        }
        if isinstance(value, m.ProcessMember | m.ContainerMember):
            data["kind"] = "process" if isinstance(value, m.ProcessMember) else "container"
        return data
    return value


def snapshot_to_json(snapshot: m.Snapshot) -> str:
    """Encode a snapshot using the explicit version-one wire contract.

    Parameters
    ----------
    snapshot : Snapshot
        Immutable observation to encode.

    Returns
    -------
    str
        JSON with integer bytes and timezone-aware ISO timestamps.
    """
    data = {
        name: encode(value=getattr(snapshot, name)) for name in SNAPSHOT_SCHEMA if name != "schema"
    }
    return json.dumps({"schema": m.SCHEMA_VERSION, **data}, ensure_ascii=False, allow_nan=False)


def snapshot_from_json(text: str) -> m.Snapshot:
    """Decode a snapshot, rejecting unknown fields and invalid values.

    Parameters
    ----------
    text : str
        Version-one snapshot JSON.

    Returns
    -------
    Snapshot
        Validated immutable observation.
    """
    try:
        if type(text) is not str:
            raise SnapshotFormatError("snapshot: expected str")
        values = fields(value=json.loads(text), schema=SNAPSHOT_SCHEMA, path="snapshot")
        values.pop("schema")
        return m.Snapshot(**values)
    except (ValueError, RecursionError) as error:
        raise SnapshotFormatError(f"snapshot: {error}") from error
