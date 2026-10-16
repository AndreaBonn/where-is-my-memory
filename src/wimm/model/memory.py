from dataclasses import dataclass

from .enums import Category
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
        require_bytes(value=self.unattributed, field="unattributed")


@dataclass(frozen=True, slots=True)
class MemorySummary(ImmutableModel):
    total: int
    available: int
    used: int
    swap_total: int
    swap_used: int
    breakdown: MemoryBreakdown

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
