import logging
from pathlib import Path

from wimm.model.raw import MemInfo

from . import CollectorResult

LOGGER = logging.getLogger(__name__)
MEMINFO_PATH = Path("/proc/meminfo")
BYTES_PER_KIB = 1024
MEMINFO_FIELDS = {
    "MemTotal": "mem_total",
    "MemFree": "mem_free",
    "MemAvailable": "mem_available",
    "Cached": "cached",
    "Buffers": "buffers",
    "SReclaimable": "s_reclaimable",
    "Shmem": "shmem",
    "SwapTotal": "swap_total",
    "SwapFree": "swap_free",
}
# Absent on some kernels (Zswap needs CONFIG_ZSWAP): a missing line counts as zero.
OPTIONAL_MEMINFO_FIELDS = {
    "SUnreclaim": "s_unreclaim",
    "KernelStack": "kernel_stack",
    "PageTables": "page_tables",
    "Zswap": "zswap",
}
ALL_MEMINFO_FIELDS = {**MEMINFO_FIELDS, **OPTIONAL_MEMINFO_FIELDS}


def parse_meminfo(text: str) -> MemInfo:
    """Parse Linux meminfo, converting its kB fields to bytes.

    Parameters
    ----------
    text : str
        Complete contents of /proc/meminfo.

    Returns
    -------
    MemInfo
        Memory counters; invalid or missing required fields raise ValueError and
        missing optional kernel counters are zero.
    """
    counters: dict[str, int] = {}
    for line in text.splitlines():
        key, separator, value = line.partition(":")
        if key not in ALL_MEMINFO_FIELDS:
            continue
        parts = value.split()
        if not separator or len(parts) != 2 or parts[1] != "kB":
            raise ValueError(f"Invalid meminfo field: {key}")
        counters[ALL_MEMINFO_FIELDS[key]] = int(parts[0]) * BYTES_PER_KIB
    if not set(MEMINFO_FIELDS.values()) <= counters.keys():
        raise ValueError("Missing required meminfo fields")
    return MemInfo(**counters)


def collect_meminfo(path: Path = MEMINFO_PATH) -> CollectorResult[MemInfo | None]:
    try:
        return CollectorResult(data=parse_meminfo(text=path.read_text()))
    except Exception as error:
        LOGGER.warning("Memory collection failed: %s", error)
        return CollectorResult(data=None, error=str(error))
