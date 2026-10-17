from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .snapshot import DockerStatus
from .validation import ImmutableModel, require_aware, require_bytes, require_nonnegative


class CacheKind(Enum):
    UV = "uv"
    NPM = "npm"
    PIP = "pip"
    THUMBNAILS = "thumbnails"
    TRASH = "trash"


def _require_text(value: str, field: str) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} must not be blank")


def _require_optional_bytes(value: int | None, field: str) -> None:
    if value is not None:
        require_bytes(value=value, field=field)


@dataclass(frozen=True, slots=True)
class DockerImage(ImmutableModel):
    """One image of `docker system df`; the three flags are independent.

    `size` is the whole image (the SIZE column); `unique_size` the part no other image
    shares, which is what removing it frees (the RECLAIMABLE column).
    """

    id: str
    tags: tuple[str, ...]
    size: int
    unique_size: int
    in_use: bool
    dangling: bool
    local_build: bool

    def __post_init__(self) -> None:
        ImmutableModel.__post_init__(self)
        _require_text(value=self.id, field="id")
        require_bytes(value=self.size, field="size")
        require_bytes(value=self.unique_size, field="unique_size")
        if self.unique_size > self.size:
            raise ValueError("unique_size must not exceed size")
        if self.dangling != (not self.tags):
            raise ValueError("dangling must match the absence of tags")


@dataclass(frozen=True, slots=True)
class DockerVolume(ImmutableModel):
    """A volume; `size` and `ref_count` are None when Docker did not compute them.

    `created_at` is Docker's `CreatedAt` string, verbatim; empty when the record lacks it.
    """

    name: str
    size: int | None
    ref_count: int | None
    created_at: str

    def __post_init__(self) -> None:
        ImmutableModel.__post_init__(self)
        _require_text(value=self.name, field="name")
        _require_optional_bytes(value=self.size, field="size")
        if self.ref_count is not None:
            require_nonnegative(value=self.ref_count, field="ref_count")

    @property
    def orphan(self) -> bool:
        return self.ref_count == 0


@dataclass(frozen=True, slots=True)
class StoppedContainer(ImmutableModel):
    id: str
    name: str
    state: str
    size: int

    def __post_init__(self) -> None:
        ImmutableModel.__post_init__(self)
        _require_text(value=self.id, field="id")
        require_bytes(value=self.size, field="size")


@dataclass(frozen=True, slots=True)
class DockerDisk(ImmutableModel):
    """Docker part of the report; the `*_truncated` counters say how many entries the cap hid.

    `build_cache_reclaimable` is the part of `build_cache_size` a prune frees: the records
    neither in use nor shared.
    """

    status: DockerStatus
    images: tuple[DockerImage, ...]
    volumes: tuple[DockerVolume, ...]
    stopped_containers: tuple[StoppedContainer, ...]
    build_cache_size: int
    build_cache_reclaimable: int
    images_truncated: int = 0
    volumes_truncated: int = 0
    containers_truncated: int = 0

    def __post_init__(self) -> None:
        ImmutableModel.__post_init__(self)
        require_bytes(value=self.build_cache_size, field="build_cache_size")
        require_bytes(value=self.build_cache_reclaimable, field="build_cache_reclaimable")
        if self.build_cache_reclaimable > self.build_cache_size:
            raise ValueError("build_cache_reclaimable must not exceed build_cache_size")
        for name in ("images_truncated", "volumes_truncated", "containers_truncated"):
            require_nonnegative(value=getattr(self, name), field=name)
        for name, ids in (
            ("images", [i.id for i in self.images]),
            ("volumes", [v.name for v in self.volumes]),
            ("stopped_containers", [c.id for c in self.stopped_containers]),
        ):
            if len(ids) != len(set(ids)):
                raise ValueError(f"{name} must have unique ids")
        has_data = bool(self.images or self.volumes or self.stopped_containers)
        if not self.status.available and (
            has_data or self.build_cache_size or self.build_cache_reclaimable
        ):
            raise ValueError("unavailable Docker must carry no data")


@dataclass(frozen=True, slots=True)
class CacheEntry(ImmutableModel):
    kind: CacheKind
    path: str
    size: int
    st_ino: int
    st_dev: int

    def __post_init__(self) -> None:
        ImmutableModel.__post_init__(self)
        _require_text(value=self.path, field="path")
        require_bytes(value=self.size, field="size")
        require_nonnegative(value=self.st_ino, field="st_ino")
        require_nonnegative(value=self.st_dev, field="st_dev")


@dataclass(frozen=True, slots=True)
class DevDir(ImmutableModel):
    """A `node_modules` or `.venv` found by the scan; `age_days` is the project's staleness."""

    path: str
    size: int
    age_days: int
    st_ino: int
    st_dev: int

    def __post_init__(self) -> None:
        ImmutableModel.__post_init__(self)
        _require_text(value=self.path, field="path")
        require_bytes(value=self.size, field="size")
        require_nonnegative(value=self.age_days, field="age_days")
        require_nonnegative(value=self.st_ino, field="st_ino")
        require_nonnegative(value=self.st_dev, field="st_dev")


@dataclass(frozen=True, slots=True)
class DiskReport(ImmutableModel):
    scanned_at: datetime
    docker: DockerDisk
    caches: tuple[CacheEntry, ...]
    devdirs: tuple[DevDir, ...]
    devdirs_truncated: int = 0

    def __post_init__(self) -> None:
        ImmutableModel.__post_init__(self)
        require_aware(value=self.scanned_at, field="scanned_at")
        require_nonnegative(value=self.devdirs_truncated, field="devdirs_truncated")
