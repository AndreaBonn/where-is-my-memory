from dataclasses import dataclass, fields
from datetime import datetime
from types import UnionType
from typing import Union, get_args, get_origin


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


COLLECTION_TYPES = (tuple, frozenset)


@dataclass(frozen=True, slots=True)
class CollectionSpec:
    kind: type
    optional: bool


def declared_collection(annotation: object) -> CollectionSpec | None:
    """Describe a tuple or frozenset annotation, plain or `| None`; None for anything else."""
    origin = get_origin(annotation)
    for kind in COLLECTION_TYPES:
        if origin is kind:
            return CollectionSpec(kind=kind, optional=False)
    if origin in (Union, UnionType):
        members = [arg for arg in get_args(annotation) if arg is not type(None)]
        inner = declared_collection(annotation=members[0]) if len(members) == 1 else None
        if inner is not None:
            return CollectionSpec(kind=inner.kind, optional=True)
    return None


def collection_matches(value: object, spec: CollectionSpec) -> bool:
    return type(value) is spec.kind or (spec.optional and value is None)


_FieldSpecs = tuple[tuple[str, CollectionSpec | None], ...]
_FIELD_SPECS: dict[type, _FieldSpecs] = {}


def _field_specs(cls: type) -> _FieldSpecs:
    """Field names and collection specs of a model class, parsed once per class.

    The sampler builds thousands of models per cycle; reading the annotations every
    time was a measurable share of its CPU (RNF-01).
    """
    specs = _FIELD_SPECS.get(cls)
    if specs is None:
        specs = tuple((f.name, declared_collection(annotation=f.type)) for f in fields(cls))
        _FIELD_SPECS[cls] = specs
    return specs


@dataclass(frozen=True, slots=True)
class ImmutableModel:
    def __post_init__(self) -> None:
        for name, spec in _field_specs(type(self)):
            value = getattr(self, name)
            if spec is not None and not collection_matches(value=value, spec=spec):
                raise ValueError(f"{name} must be a {spec.kind.__name__}")
            require_immutable(value=value, field=name)
            if isinstance(value, datetime):
                require_aware(value=value, field=name)


MAX_PORT = 65535


def require_nonnegative(value: int, field: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field} must be a nonnegative integer")


def require_ports(values: tuple[int, ...], field: str) -> None:
    for value in values:
        require_nonnegative(value=value, field=field)
        if value > MAX_PORT:
            raise ValueError(f"{field} must be in 0..{MAX_PORT}")
