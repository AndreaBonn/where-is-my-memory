from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from .cache_items import CacheItem, CacheRest
from .snapshot import DockerStatus
from .validation import (
    ImmutableModel,
    require_aware,
    require_bytes,
    require_nonnegative,
    require_text,
)


class CacheKind(Enum):
    UV = "uv"
    NPM = "npm"
    PIP = "pip"
    THUMBNAILS = "thumbnails"
    TRASH = "trash"
    CARGO_REGISTRY = "cargo_registry"
    CARGO_GIT = "cargo_git"
    GRADLE = "gradle"
    MAVEN = "maven"
    GO_MOD = "go_mod"
    GO_BUILD = "go_build"
    YARN = "yarn"
    PNPM = "pnpm"
    BUN = "bun"
    CONDA = "conda"
    PLAYWRIGHT = "playwright"
    JETBRAINS = "jetbrains"
    HUGGINGFACE = "huggingface"
    OLLAMA = "ollama"
    OLLAMA_SYSTEM = "ollama_system"
    ANDROID_AVD = "android_avd"
    ANDROID_SDK = "android_sdk"


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
        require_text(value=self.id, field="id")
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
        require_text(value=self.name, field="name")
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
        require_text(value=self.id, field="id")
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
    """A known cache folder; `items` are its parts, `rest` what no item owns.

    The collector makes items plus rest add up to `size`; the model only refuses a sum
    above it, which no measurement can produce.
    """

    kind: CacheKind
    path: str
    size: int
    st_ino: int
    st_dev: int
    items: tuple[CacheItem, ...] = ()
    rest: CacheRest = field(default_factory=CacheRest)

    def __post_init__(self) -> None:
        ImmutableModel.__post_init__(self)
        require_text(value=self.path, field="path")
        require_bytes(value=self.size, field="size")
        require_nonnegative(value=self.st_ino, field="st_ino")
        require_nonnegative(value=self.st_dev, field="st_dev")
        ids = [item.id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("items must have unique ids")
        accounted = sum(item.size for item in self.items) + self.rest.shared
        if accounted + self.rest.unattributed > self.size:
            raise ValueError("items and rest must not exceed size")
        if self.kind is CacheKind.OLLAMA_SYSTEM:
            _require_system_store(entry=self)


def _require_system_store(*, entry: CacheEntry) -> None:
    """The system ollama store has no file behind it: no inode, no rest, items with an id."""
    if entry.st_ino != 0 or entry.st_dev != 0:
        raise ValueError("a system ollama store has no file: st_ino and st_dev must be 0")
    if entry.rest != CacheRest():
        raise ValueError("a system ollama store has no rest")
    if any(not item.model_id for item in entry.items):
        raise ValueError("every system ollama item needs a model_id")


@dataclass(frozen=True, slots=True)
class DevDir(ImmutableModel):
    """A rebuildable folder found by the scan; `age_days` is the project's staleness.

    `marker` is the project file that qualified the folder (`Cargo.toml` for a `target`),
    empty when the name alone was enough or the report predates the field.
    """

    path: str
    size: int
    age_days: int
    st_ino: int
    st_dev: int
    marker: str = ""

    def __post_init__(self) -> None:
        ImmutableModel.__post_init__(self)
        require_text(value=self.path, field="path")
        require_bytes(value=self.size, field="size")
        require_nonnegative(value=self.age_days, field="age_days")
        require_nonnegative(value=self.st_ino, field="st_ino")
        require_nonnegative(value=self.st_dev, field="st_dev")
        if type(self.marker) is not str:
            raise ValueError("marker must be text")


@dataclass(frozen=True, slots=True)
class DiskReport(ImmutableModel):
    """`ollama_served` is the value of the ollama server situation S0-S3 the scan saw ("" if
    the scan did not look); it decides which ollama models the page may offer to remove."""

    scanned_at: datetime
    docker: DockerDisk
    caches: tuple[CacheEntry, ...]
    devdirs: tuple[DevDir, ...]
    devdirs_truncated: int = 0
    ollama_served: str = ""

    def __post_init__(self) -> None:
        ImmutableModel.__post_init__(self)
        require_aware(value=self.scanned_at, field="scanned_at")
        require_nonnegative(value=self.devdirs_truncated, field="devdirs_truncated")
        if type(self.ollama_served) is not str:
            raise ValueError("ollama_served must be text")
