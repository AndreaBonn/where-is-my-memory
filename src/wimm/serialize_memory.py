"""Wire form of the memory summary, its breakdown and the video memory."""

from typing import Any

from wimm import model as m
from wimm.wire_decoders import (
    Schema,
    SnapshotFormatError,
    byte_count,
    enumeration,
    fields,
    primitive,
    sequence,
)

BREAKDOWN_VOICES = (
    "kernel_cache",
    "unattributed",
    "shared_tmpfs",
    "kernel_unreclaimable",
    "zram",
    "zswap",
)
GPU_MEMORY_SCHEMA: Schema = {
    "vendor": enumeration(enum=m.GpuVendor),
    "used_bytes": byte_count,
    "total_bytes": byte_count,
}


def breakdown(value: Any, path: str) -> m.MemoryBreakdown:
    data = primitive(expected=dict)(value, path)
    schema: Schema = {name: byte_count for name in BREAKDOWN_VOICES}
    schema.update({name: byte_count for name in data if name in m.Category.__members__})
    values = fields(value=data, schema=schema, path=path)
    categories = tuple(
        (m.Category[name], size) for name, size in values.items() if name in m.Category.__members__
    )
    return m.MemoryBreakdown(
        categories=categories, **{name: values[name] for name in BREAKDOWN_VOICES}
    )


def encode_breakdown(value: m.MemoryBreakdown) -> dict[str, int]:
    return {
        **{category.name: size for category, size in value.categories},
        **{name: getattr(value, name) for name in BREAKDOWN_VOICES},
    }


def gpu_memory(value: Any, path: str) -> m.GpuMemory:
    values = fields(value=value, schema=GPU_MEMORY_SCHEMA, path=path)
    try:
        return m.GpuMemory(**values)
    except ValueError as error:
        raise SnapshotFormatError(f"{path}: {error}") from error


MEMORY_SUMMARY_SCHEMA: Schema = {
    "total": byte_count,
    "available": byte_count,
    "used": byte_count,
    "swap_total": byte_count,
    "swap_used": byte_count,
    "breakdown": breakdown,
    "video": sequence(decoder=gpu_memory),
}
