import json
from collections.abc import Callable
from datetime import datetime
from enum import Enum
from typing import Any

from wimm.wire_decoders import (
    BOOLEAN,
    INTEGER,
    TEXT,
    Schema,
    byte_count,
    enumeration,
    fields,
    float_value,
    literal,
    nullable,
    primitive,
    sequence,
    timestamp,
)
from wimm.wire_decoders import (
    SnapshotFormatError as SnapshotFormatError,
)

from . import model as m
from .serialize_memory import GPU_MEMORY_SCHEMA, MEMORY_SUMMARY_SCHEMA, encode_breakdown


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


def member(value: Any, path: str) -> m.Member:
    data = primitive(expected=dict)(value, path)
    kind = data.get("kind")
    if kind == "process":
        return record(cls=m.ProcessMember)(value, path)
    if kind == "container":
        return record(cls=m.ContainerMember)(value, path)
    raise SnapshotFormatError(f"{path}.kind: expected process or container")


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
        "tool_label": nullable(decoder=TEXT),
        "tool_reason": nullable(decoder=TEXT),
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
        "growth": nullable(decoder=record(cls=m.GroupGrowth)),
    },
    m.GroupGrowth: {"delta_bytes": byte_count, "span_s": INTEGER},
    m.MemorySummary: MEMORY_SUMMARY_SCHEMA,
    m.GpuMemory: GPU_MEMORY_SCHEMA,
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
        return encode_breakdown(value=value)
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
    """Encode a snapshot using the explicit version-four wire contract.

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
        Version-four snapshot JSON.

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
