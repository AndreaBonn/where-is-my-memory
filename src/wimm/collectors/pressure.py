import logging
import os
from pathlib import Path

from wimm.core.constants import USER_UNIT_TEMPLATE
from wimm.model.raw import PsiSample

LOGGER = logging.getLogger(__name__)
PSI_PATH = Path("/proc/pressure/memory")
CGROUP_ROOT = Path("/sys/fs/cgroup")
EVENTS_FILE = "memory.events"
OOM_KILL_KEY = "oom_kill"
PSI_SOME = "some"
PSI_FULL = "full"
PSI_AVG60 = "avg60"


def _avg60(*, line: str) -> float | None:
    for field in line.split()[1:]:
        key, _separator, value = field.partition("=")
        if key == PSI_AVG60:
            try:
                return float(value)
            except ValueError:
                return None
    return None


def parse_psi(text: str) -> PsiSample | None:
    """Parse the ``some`` and ``full`` lines of /proc/pressure/memory; None if either is missing."""
    found: dict[str, float | None] = {PSI_SOME: None, PSI_FULL: None}
    for line in text.splitlines():
        kind = line.split(maxsplit=1)[0] if line.strip() else ""
        if kind in found:
            found[kind] = _avg60(line=line)
    some, full = found[PSI_SOME], found[PSI_FULL]
    if some is None or full is None:
        return None
    try:
        return PsiSample(some_avg60=some, full_avg60=full)
    except ValueError as error:
        LOGGER.debug("PSI out of range: %s", error)
        return None


def read_psi(*, path: Path = PSI_PATH) -> PsiSample | None:
    try:
        return parse_psi(path.read_text())
    except OSError as error:
        LOGGER.debug("PSI not readable: %s", error)
        return None


def parse_oom_kill(text: str) -> int | None:
    """Return the ``oom_kill`` counter of a memory.events file, None if absent or invalid."""
    for line in text.splitlines():
        key, _separator, value = line.partition(" ")
        if key == OOM_KILL_KEY:
            return int(value) if value.strip().isdecimal() else None
    return None


def read_oom_kills(*, uid: int | None = None, cgroup_root: Path = CGROUP_ROOT) -> int | None:
    """OOM kills counted in the user's ``user@<uid>.service`` cgroup."""
    owner = os.getuid() if uid is None else uid
    unit = cgroup_root / f"user.slice/user-{owner}.slice" / USER_UNIT_TEMPLATE.format(uid=owner)
    try:
        return parse_oom_kill((unit / EVENTS_FILE).read_text())
    except OSError as error:
        LOGGER.debug("OOM counter not readable: %s", error)
        return None
