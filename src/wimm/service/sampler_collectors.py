from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial

from wimm.collectors import CollectorResult
from wimm.collectors.desktop_entries import DesktopEntry, DesktopEntryIndex
from wimm.collectors.disk import collect_disk_usage
from wimm.collectors.docker_source import DockerSample, DockerSource
from wimm.collectors.meminfo import collect_meminfo
from wimm.collectors.processes import collect_processes
from wimm.collectors.sockets import collect_sockets
from wimm.model.memory import DiskUsage
from wimm.model.raw import MemInfo, RawProcess, RawSocket

from .sampler_environment import SamplerEnvironment


@dataclass(frozen=True)
class Collectors:
    processes: Callable[[], CollectorResult[tuple[RawProcess, ...]]]
    sockets: Callable[[], CollectorResult[tuple[RawSocket, ...]]]
    docker: Callable[[], CollectorResult[DockerSample]]
    meminfo: Callable[[], CollectorResult[MemInfo | None]]
    disks: Callable[[], CollectorResult[tuple[DiskUsage, ...]]]
    desktop: Callable[[], CollectorResult[Mapping[str, DesktopEntry]]]


def default_collectors(*, environment: SamplerEnvironment) -> Collectors:
    return Collectors(
        processes=partial(collect_processes, own_uid=environment.uid),
        sockets=collect_sockets,
        docker=DockerSource().collect,
        meminfo=collect_meminfo,
        disks=partial(collect_disk_usage, home=environment.home),
        desktop=DesktopEntryIndex().collect,
    )
