import logging
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from wimm.model.raw import KernelMemory

LOGGER = logging.getLogger(__name__)
SYS_BLOCK = Path("/sys/block")
MOUNTINFO_PATH = Path("/proc/self/mountinfo")
# https://docs.kernel.org/admin-guide/blockdev/zram.html: mm_stat lists orig_data_size,
# compr_data_size, mem_used_total, ... in bytes, so mem_used_total is the third field.
MM_STAT_MEM_USED_TOTAL_INDEX = 2
TMPFS = "tmpfs"
MOUNTINFO_SEPARATOR = " - "
MOUNTINFO_DEVICE_INDEX = 2
MOUNTINFO_MOUNTPOINT_INDEX = 4
OCTAL_ESCAPE = re.compile(r"\\([0-7]{3})")


class StatVfsResult(Protocol):
    @property
    def f_blocks(self) -> int: ...

    @property
    def f_bfree(self) -> int: ...

    @property
    def f_frsize(self) -> int: ...


StatVfs = Callable[[str], StatVfsResult]


def _zram_device_bytes(device: Path) -> int:
    try:
        used = int((device / "mm_stat").read_text().split()[MM_STAT_MEM_USED_TOTAL_INDEX])
        if used < 0:
            raise ValueError("negative mem_used_total")
        return used
    except (OSError, ValueError, IndexError) as error:
        LOGGER.debug("zram mm_stat unreadable for %s: %s", device.name, error)
        return 0


def read_zram_bytes(sys_block: Path = SYS_BLOCK) -> int:
    """Sum `mem_used_total` over every zram device; unreadable devices count zero.

    Parameters
    ----------
    sys_block : Path
        Directory holding the block devices (`/sys/block`).
    """
    try:
        devices = sorted(sys_block.glob("zram*"))
    except OSError as error:
        LOGGER.debug("zram scan failed: %s", error)
        return 0
    return sum(_zram_device_bytes(device=device) for device in devices)


def _tmpfs_mounts(text: str) -> dict[str, list[str]]:
    """Map device id to the mount points of each tmpfs, bind mounts in mountinfo order."""
    mounts: dict[str, list[str]] = {}
    for line in text.splitlines():
        head, separator, tail = line.partition(MOUNTINFO_SEPARATOR)
        fields = head.split()
        if not separator or len(fields) <= MOUNTINFO_MOUNTPOINT_INDEX:
            continue
        if tail.split(maxsplit=1)[:1] != [TMPFS]:
            continue
        mountpoint = OCTAL_ESCAPE.sub(
            lambda m: chr(int(m.group(1), 8)), fields[MOUNTINFO_MOUNTPOINT_INDEX]
        )
        mounts.setdefault(fields[MOUNTINFO_DEVICE_INDEX], []).append(mountpoint)
    return mounts


def _used_bytes(mountpoints: list[str], statvfs: StatVfs) -> int:
    """Used bytes of one tmpfs, from the first of its mount points that answers."""
    for mountpoint in mountpoints:
        try:
            stat = statvfs(mountpoint)
        except OSError as error:
            LOGGER.debug("statvfs failed for %s: %s", mountpoint, error)
            continue
        return max(0, (stat.f_blocks - stat.f_bfree) * stat.f_frsize)
    return 0


def read_tmpfs_used_bytes(mountinfo: Path = MOUNTINFO_PATH, statvfs: StatVfs = os.statvfs) -> int:
    """Sum used bytes of the tmpfs mounts, counting each filesystem once.

    Only `tmpfs` entries are probed, so network mounts are never touched. Unreadable
    mountinfo or a failing mount point contributes zero.

    Parameters
    ----------
    mountinfo : Path
        Mount table in `/proc/self/mountinfo` format.
    statvfs : Callable[[str], StatVfsResult]
        Injected `os.statvfs`.
    """
    try:
        mounts = _tmpfs_mounts(text=mountinfo.read_text())
    except OSError as error:
        LOGGER.debug("mountinfo unreadable: %s", error)
        return 0
    return sum(_used_bytes(mountpoints=points, statvfs=statvfs) for points in mounts.values())


def collect_kernel_memory(
    sys_block: Path = SYS_BLOCK,
    mountinfo: Path = MOUNTINFO_PATH,
    statvfs: StatVfs = os.statvfs,
) -> KernelMemory:
    """Return zram and tmpfs usage in bytes; each failing source reads as zero."""
    return KernelMemory(
        zram=read_zram_bytes(sys_block=sys_block),
        tmpfs_used=read_tmpfs_used_bytes(mountinfo=mountinfo, statvfs=statvfs),
    )
