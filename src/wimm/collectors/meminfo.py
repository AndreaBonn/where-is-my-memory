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


def parse_meminfo(text: str) -> MemInfo:
    """Parse Linux meminfo, converting its kB fields to bytes.

    Parameters
    ----------
    text : str
        Complete contents of /proc/meminfo.

    Returns
    -------
    MemInfo
        Required memory counters; invalid or missing fields raise ValueError.
    """
    counters: dict[str, int] = {}
    for line in text.splitlines():
        key, separator, value = line.partition(":")
        if key not in MEMINFO_FIELDS:
            continue
        parts = value.split()
        if not separator or len(parts) != 2 or parts[1] != "kB":
            raise ValueError(f"Invalid meminfo field: {key}")
        counters[MEMINFO_FIELDS[key]] = int(parts[0]) * BYTES_PER_KIB
    if counters.keys() != set(MEMINFO_FIELDS.values()):
        raise ValueError("Missing required meminfo fields")
    return MemInfo(**counters)


def collect_meminfo(path: Path = MEMINFO_PATH) -> CollectorResult[MemInfo | None]:
    try:
        return CollectorResult(data=parse_meminfo(text=path.read_text()))
    except Exception as error:
        LOGGER.warning("Memory collection failed: %s", error)
        return CollectorResult(data=None, error=str(error))
