from dataclasses import dataclass

from .enums import MetricsSource
from .validation import ImmutableModel, require_bytes, require_nonnegative, require_ports


@dataclass(frozen=True, slots=True)
class Mount(ImmutableModel):
    type: str
    source: str
    destination: str


@dataclass(frozen=True, slots=True)
class RawProcess(ImmutableModel):
    pid: int
    ppid: int
    uid: int
    name: str
    exe: str | None
    cmdline: tuple[str, ...] | None
    cwd: str | None
    create_time: float | None
    cpu_time_s: float | None
    pss: int | None
    uss: int | None
    swap: int | None
    rss: int
    cgroup: str
    terminal: str | None
    tpgid: int | None
    pgid: int | None

    def __post_init__(self) -> None:
        ImmutableModel.__post_init__(self)
        for name in ("pid", "ppid"):
            require_nonnegative(value=getattr(self, name), field=name)
        for name in ("pgid", "tpgid"):
            group_id = getattr(self, name)
            if group_id is not None:
                require_nonnegative(value=group_id, field=name)
        require_bytes(value=self.rss, field="rss")
        for name in ("pss", "uss", "swap"):
            value = getattr(self, name)
            if value is not None:
                require_bytes(value=value, field=name)

    @property
    def is_foreground(self) -> bool:
        return self.tpgid is not None and self.tpgid == self.pgid


@dataclass(frozen=True, slots=True)
class RawSocket(ImmutableModel):
    pid: int | None
    laddr: tuple[str, int] | None
    raddr: tuple[str, int] | None
    status: str

    def __post_init__(self) -> None:
        ImmutableModel.__post_init__(self)
        if self.pid is not None:
            require_nonnegative(value=self.pid, field="pid")
        for name in ("laddr", "raddr"):
            address = getattr(self, name)
            if address is not None:
                require_ports(values=(address[1],), field=name)


@dataclass(frozen=True, slots=True)
class RawContainer(ImmutableModel):
    id: str
    name: str
    image: str
    state: str
    labels: tuple[tuple[str, str], ...]
    mounts: tuple[Mount, ...]
    ports: tuple[int, ...]
    pid: int
    memory_bytes: int
    cpu_usage_usec: int
    net_bytes: int | None
    metrics_source: MetricsSource

    def __post_init__(self) -> None:
        ImmutableModel.__post_init__(self)
        require_nonnegative(value=self.pid, field="pid")
        require_nonnegative(value=self.cpu_usage_usec, field="cpu_usage_usec")
        require_ports(values=self.ports, field="ports")
        require_bytes(value=self.memory_bytes, field="memory_bytes")
        if self.net_bytes is not None:
            require_bytes(value=self.net_bytes, field="net_bytes")


@dataclass(frozen=True, slots=True)
class MemInfo(ImmutableModel):
    mem_total: int
    mem_free: int
    mem_available: int
    cached: int
    buffers: int
    s_reclaimable: int
    shmem: int
    swap_total: int
    swap_free: int

    def __post_init__(self) -> None:
        ImmutableModel.__post_init__(self)
        for name in self.__slots__:
            require_bytes(value=getattr(self, name), field=name)
