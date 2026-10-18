"""JSON wire form of the disk report (SPECIFICHE 6.5, `GetDiskReport`).

Same contract as the snapshot in `wimm.serialize`: integer bytes, timezone-aware ISO
dates, unknown and missing fields rejected. It lives here because `serialize.py` is at
the 300-line limit; the decoding primitives come from `wimm.wire_decoders`.
"""

import json
from dataclasses import fields as dataclass_fields
from datetime import datetime
from enum import Enum
from typing import Any

from wimm import model as m
from wimm.wire_decoders import (
    BOOLEAN,
    INTEGER,
    TEXT,
    Decoder,
    Schema,
    SnapshotFormatError,
    byte_count,
    enumeration,
    literal,
    nullable,
    sequence,
    timestamp,
)
from wimm.wire_decoders import fields as decode_fields

__all__ = ["disk_report_from_json", "disk_report_to_json"]

OPTIONAL_BYTES = nullable(decoder=byte_count)
OPTIONAL_INTEGER = nullable(decoder=INTEGER)


# Fields added after the first release: a report written without them decodes to the
# default, and the encoder leaves them out while they hold it, so old readers still parse.
OPTIONAL_FIELDS: dict[type, dict[str, Any]] = {m.DevDir: {"marker": ""}}


def _record[T](cls: type[T]) -> Decoder:
    def decode(value: Any, path: str) -> T:
        if isinstance(value, dict):
            value = {**OPTIONAL_FIELDS.get(cls, {}), **value}
        values = decode_fields(value=value, schema=SCHEMAS[cls], path=path)
        try:
            return cls(**values)
        except ValueError as error:
            raise SnapshotFormatError(f"{path}: {error}") from error

    return decode


SCHEMAS: dict[type, Schema] = {
    m.DockerStatus: {"available": BOOLEAN, "error": nullable(decoder=TEXT)},
    m.DockerImage: {
        "id": TEXT,
        "tags": sequence(decoder=TEXT),
        "size": byte_count,
        "unique_size": byte_count,
        "in_use": BOOLEAN,
        "dangling": BOOLEAN,
        "local_build": BOOLEAN,
    },
    m.DockerVolume: {
        "name": TEXT,
        "size": OPTIONAL_BYTES,
        "ref_count": OPTIONAL_INTEGER,
        "created_at": TEXT,
    },
    m.StoppedContainer: {"id": TEXT, "name": TEXT, "state": TEXT, "size": byte_count},
    m.DockerDisk: {
        "status": _record(cls=m.DockerStatus),
        "images": sequence(decoder=_record(cls=m.DockerImage)),
        "volumes": sequence(decoder=_record(cls=m.DockerVolume)),
        "stopped_containers": sequence(decoder=_record(cls=m.StoppedContainer)),
        "build_cache_size": byte_count,
        "build_cache_reclaimable": byte_count,
        "images_truncated": INTEGER,
        "volumes_truncated": INTEGER,
        "containers_truncated": INTEGER,
    },
    m.CacheEntry: {
        "kind": enumeration(enum=m.CacheKind),
        "path": TEXT,
        "size": byte_count,
        "st_ino": INTEGER,
        "st_dev": INTEGER,
    },
    m.DevDir: {
        "path": TEXT,
        "size": byte_count,
        "age_days": INTEGER,
        "st_ino": INTEGER,
        "st_dev": INTEGER,
        "marker": TEXT,
    },
}
REPORT_SCHEMA: Schema = {
    "schema": literal(expected=m.SCHEMA_VERSION),
    "scanned_at": timestamp,
    "docker": _record(cls=m.DockerDisk),
    "caches": sequence(decoder=_record(cls=m.CacheEntry)),
    "devdirs": sequence(decoder=_record(cls=m.DevDir)),
    "devdirs_truncated": INTEGER,
}


def _encode(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_encode(value=item) for item in value]
    if type(value) in SCHEMAS:
        defaults = OPTIONAL_FIELDS.get(type(value), {})
        return {
            f.name: _encode(value=getattr(value, f.name))
            for f in dataclass_fields(value)
            if f.name not in defaults or getattr(value, f.name) != defaults[f.name]
        }
    return value


def disk_report_to_json(*, report: m.DiskReport) -> str:
    """Encode a disk report as version-one JSON."""
    data = {
        name: _encode(value=getattr(report, name)) for name in REPORT_SCHEMA if name != "schema"
    }
    return json.dumps({"schema": m.SCHEMA_VERSION, **data}, ensure_ascii=False, allow_nan=False)


def disk_report_from_json(*, text: str) -> m.DiskReport:
    """Decode a disk report, rejecting unknown fields and invalid values."""
    try:
        if type(text) is not str:
            raise SnapshotFormatError("disk report: expected str")
        values = decode_fields(value=json.loads(text), schema=REPORT_SCHEMA, path="disk report")
        values.pop("schema")
        return m.DiskReport(**values)
    except (ValueError, RecursionError) as error:
        raise SnapshotFormatError(f"disk report: {error}") from error
