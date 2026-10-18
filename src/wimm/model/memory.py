from dataclasses import dataclass

from .enums import Category, GpuVendor
from .validation import ImmutableModel, require_bytes


@dataclass(frozen=True, slots=True)
class MemoryUse(ImmutableModel):
    used: int
    reclaimable: int

    def __post_init__(self) -> None:
        ImmutableModel.__post_init__(self)
        require_bytes(value=self.used, field="used")
        require_bytes(value=self.reclaimable, field="reclaimable")


@dataclass(frozen=True, slots=True)
class MemoryBreakdown(ImmutableModel):
    categories: tuple[tuple[Category, int], ...]
    kernel_cache: int
    unattributed: int
    shared_tmpfs: int = 0
    kernel_unreclaimable: int = 0
    zram: int = 0
    zswap: int = 0

    def __post_init__(self) -> None:
        ImmutableModel.__post_init__(self)
        names = tuple(category for category, _ in self.categories)
        if len(names) != len(set(names)):
            raise ValueError("categories must be unique")
        if Category.PROJECT in names:
            raise ValueError("PROJECT memory must be split across member categories")
        for category, size in self.categories:
            require_bytes(value=size, field=f"categories.{category.name}")
        require_bytes(value=self.kernel_cache, field="kernel_cache")
        for name in ("unattributed", "shared_tmpfs", "kernel_unreclaimable", "zram", "zswap"):
            require_bytes(value=getattr(self, name), field=name)


@dataclass(frozen=True, slots=True)
class GpuMemory(ImmutableModel):
    vendor: GpuVendor
    used_bytes: int
    total_bytes: int

    def __post_init__(self) -> None:
        ImmutableModel.__post_init__(self)
        if not isinstance(self.vendor, GpuVendor):
            raise ValueError("vendor must be a GpuVendor")
        require_bytes(value=self.used_bytes, field="used_bytes")
        require_bytes(value=self.total_bytes, field="total_bytes")


@dataclass(frozen=True, slots=True)
class MemorySummary(ImmutableModel):
    total: int
    available: int
    used: int
    swap_total: int
    swap_used: int
    breakdown: MemoryBreakdown
    video: tuple[GpuMemory, ...] = ()

    def __post_init__(self) -> None:
        ImmutableModel.__post_init__(self)
        for name in ("total", "available", "used", "swap_total", "swap_used"):
            require_bytes(value=getattr(self, name), field=name)


@dataclass(frozen=True, slots=True)
class DiskUsage(ImmutableModel):
    mount: str
    total: int
    used: int
    free: int

    def __post_init__(self) -> None:
        ImmutableModel.__post_init__(self)
        for name in ("total", "used", "free"):
            require_bytes(value=getattr(self, name), field=name)


@dataclass(frozen=True, slots=True)
class Reclaimable(ImmutableModel):
    ram: int
    disk: int

    def __post_init__(self) -> None:
        ImmutableModel.__post_init__(self)
        require_bytes(value=self.ram, field="ram")
        require_bytes(value=self.disk, field="disk")
