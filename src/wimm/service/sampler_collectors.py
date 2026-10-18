import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial
from typing import Protocol

from wimm.collectors import CollectorResult
from wimm.collectors.desktop_entries import DesktopEntry, DesktopEntryIndex
from wimm.collectors.disk import collect_disk_usage
from wimm.collectors.docker_source import DockerSample, DockerSource
from wimm.collectors.foreground import ForegroundReader, ForegroundState
from wimm.collectors.gpu import GpuCollector
from wimm.collectors.kernel_memory import collect_kernel_memory
from wimm.collectors.meminfo import collect_meminfo
from wimm.collectors.pressure import read_psi
from wimm.collectors.processes import collect_processes
from wimm.collectors.sockets import collect_sockets
from wimm.core.memory import NO_KERNEL_MEMORY
from wimm.model.memory import DiskUsage, GpuMemory
from wimm.model.raw import KernelMemory, MemInfo, PsiSample, RawProcess, RawSocket

from .sampler_environment import SamplerEnvironment

LOGGER = logging.getLogger(__name__)


class ForegroundSource(Protocol):
    def read(self) -> ForegroundState: ...


# Without a session type the reader stays disabled, so tests never spawn xprop.
INERT_FOREGROUND = partial(ForegroundReader, session_type=None)


@dataclass(frozen=True)
class Collectors:
    processes: Callable[[], CollectorResult[tuple[RawProcess, ...]]]
    sockets: Callable[[], CollectorResult[tuple[RawSocket, ...]]]
    docker: Callable[[], CollectorResult[DockerSample]]
    meminfo: Callable[[], CollectorResult[MemInfo | None]]
    disks: Callable[[], CollectorResult[tuple[DiskUsage, ...]]]
    desktop: Callable[[], CollectorResult[Mapping[str, DesktopEntry]]]
    # Builds the foreground reader; called with ``enabled=`` whenever the config toggles it.
    foreground: Callable[..., ForegroundSource] = INERT_FOREGROUND
    # Neutral defaults: a Collectors built without them reads no kernel voices, GPU or PSI.
    kernel_memory: Callable[[], KernelMemory] = lambda: NO_KERNEL_MEMORY
    video: Callable[[], tuple[GpuMemory, ...]] = tuple
    psi: Callable[[], PsiSample | None] = lambda: None


def default_collectors(*, environment: SamplerEnvironment) -> Collectors:
    return Collectors(
        processes=partial(collect_processes, own_uid=environment.uid),
        sockets=collect_sockets,
        docker=DockerSource().collect,
        meminfo=collect_meminfo,
        disks=partial(collect_disk_usage, home=environment.home),
        desktop=DesktopEntryIndex().collect,
        foreground=ForegroundReader.from_environment,
        kernel_memory=collect_kernel_memory,
        video=GpuCollector().collect,
        psi=read_psi,
    )


def safe_read[T](reader: Callable[[], T], *, neutral: T, name: str) -> T:
    """Run a collector; one that raises reads as ``neutral`` instead of breaking the cycle.

    An unreadable source (OSError) is expected and logged at debug; any other exception is
    a bug in the collector, logged as a warning with its traceback so it does not go unseen.
    """
    try:
        return reader()
    except OSError as error:
        LOGGER.debug("Collector %s failed, using the neutral value: %s", name, error)
    except Exception:
        LOGGER.warning(
            "Collector %s raised unexpectedly, using the neutral value", name, exc_info=True
        )
    return neutral
