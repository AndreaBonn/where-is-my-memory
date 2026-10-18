"""Which distribution family runs the app, from the text of the os-release file."""

import logging
from enum import StrEnum
from pathlib import Path

LOGGER = logging.getLogger(__name__)
# freedesktop os-release: /etc first, /usr/lib when /etc/os-release does not exist.
OS_RELEASE_PATHS = (Path("/etc/os-release"), Path("/usr/lib/os-release"))
QUOTES = "\"'"


class DistroFamily(StrEnum):
    UBUNTU = "ubuntu"
    FEDORA = "fedora"
    ARCH = "arch"
    DEBIAN = "debian"
    OTHER = "other"


# Order matters: Ubuntu derivatives list "debian" too in ID_LIKE, and must win over it.
_FAMILIES = (DistroFamily.UBUNTU, DistroFamily.FEDORA, DistroFamily.ARCH, DistroFamily.DEBIAN)


def parse_os_release(*, text: str) -> dict[str, str]:
    """KEY=value lines to a dict: quotes removed, comments and malformed lines skipped."""
    fields: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _sep, value = line.partition("=")
        # Shell escapes (\", \$) are not undone: ID and ID_LIKE, the fields read, never use them.
        fields[key.strip()] = value.strip().strip(QUOTES)
    return fields


def distro_family(*, text: str) -> DistroFamily:
    """The family named by ID or ID_LIKE; anything unrecognised, or empty text, is OTHER."""
    fields = parse_os_release(text=text)
    names = {fields.get("ID", ""), *fields.get("ID_LIKE", "").split()}
    return next((family for family in _FAMILIES if family.value in names), DistroFamily.OTHER)


def read_os_release(*, paths: tuple[Path, ...] = OS_RELEASE_PATHS) -> str:
    """The text of the first readable file of ``paths``, or "" when none can be read."""
    for path in paths:
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, ValueError):
            LOGGER.debug("Could not read %s", path)
    LOGGER.info("No readable os-release file, using the generic tray hint")
    return ""
