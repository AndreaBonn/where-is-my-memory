import logging
import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from wimm.model.memory import DiskUsage

from . import CollectorResult

LOGGER = logging.getLogger(__name__)
ROOT = Path("/")


class DeviceStat(Protocol):
    @property
    def st_dev(self) -> int: ...


class Usage(Protocol):
    @property
    def total(self) -> int: ...

    @property
    def used(self) -> int: ...

    @property
    def free(self) -> int: ...


def find_mount(path: Path, stat: Callable[[Path], DeviceStat]) -> Path:
    device = stat(path).st_dev
    while path != path.parent and stat(path.parent).st_dev == device:
        path = path.parent
    return path


def collect_disk_usage(
    home: Path | None = None,
    stat: Callable[[Path], DeviceStat] = os.stat,
    usage: Callable[[Path], Usage] = shutil.disk_usage,
) -> CollectorResult[tuple[DiskUsage, ...]]:
    """Read root and distinct home usage, retaining root counters on home errors.

    Parameters
    ----------
    home : Path or None
        Home directory, resolved at collection time.
    stat, usage : callable
        Device and capacity lookups.
    """
    counters: tuple[DiskUsage, ...] = ()
    try:
        root_usage = usage(ROOT)
        counters = (
            DiskUsage(
                mount=str(ROOT), total=root_usage.total, used=root_usage.used, free=root_usage.free
            ),
        )
        return CollectorResult(
            data=counters + read_home_disk_usage(home=home, stat=stat, usage=usage)
        )
    except Exception as error:
        LOGGER.warning("Disk collection failed: %s", error)
        return CollectorResult(data=counters, error=str(error))


def read_home_disk_usage(
    home: Path | None, stat: Callable[[Path], DeviceStat], usage: Callable[[Path], Usage]
) -> tuple[DiskUsage, ...]:
    home = (home if home is not None else Path.home()).resolve()
    if stat(home).st_dev == stat(ROOT).st_dev:
        return ()
    mount = find_mount(path=home, stat=stat)
    item = usage(mount)
    return (DiskUsage(mount=str(mount), total=item.total, used=item.used, free=item.free),)
