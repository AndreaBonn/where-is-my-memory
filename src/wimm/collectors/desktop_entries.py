import configparser
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from . import CollectorResult

LOGGER = logging.getLogger(__name__)
DESKTOP_SECTION = "Desktop Entry"
SYSTEM_DIRECTORIES = (
    Path("/usr/share/applications"),
    Path("/var/lib/snapd/desktop/applications"),
    Path("/var/lib/flatpak/exports/share/applications"),
)


@dataclass(frozen=True, slots=True)
class DesktopEntry:
    name: str
    categories: tuple[str, ...]


def default_directories() -> tuple[Path, ...]:
    return (
        *SYSTEM_DIRECTORIES,
        Path.home() / ".local/share/applications",
    )


def read_desktop_entry(path: Path) -> tuple[DesktopEntry, str | None] | None:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read_string(string=path.read_text(encoding="utf-8"))
        entry = parser[DESKTOP_SECTION]
        name = entry.get("Name[it_IT]", entry.get("Name[it]", entry.get("Name", "")))
        if not name:
            raise ValueError("Desktop entry has no name")
        categories = tuple(value for value in entry.get("Categories", "").split(";") if value)
        return DesktopEntry(name=name, categories=categories), entry.get("StartupWMClass")
    except (configparser.Error, KeyError, ValueError, OSError, UnicodeDecodeError) as error:
        LOGGER.debug("Skipping malformed desktop entry %s: %s", path, error)
        return None


def directory_stamp(path: Path) -> tuple[int, int] | None:
    try:
        directory_mtime = path.stat().st_mtime_ns
    except FileNotFoundError:
        return None
    latest_mtime = 0
    for entry in path.glob("*.desktop"):
        try:
            latest_mtime = max(latest_mtime, entry.stat().st_mtime_ns)
        except OSError as error:
            LOGGER.debug("Cannot stat desktop entry %s: %s", entry, error)
    return directory_mtime, latest_mtime


def build_index(directories: tuple[Path, ...]) -> Mapping[str, DesktopEntry]:
    entries: dict[str, DesktopEntry] = {}
    aliases: dict[str, DesktopEntry] = {}
    for directory in directories:
        if directory_stamp(path=directory) is None:
            continue
        for path in sorted(directory.iterdir()):
            if path.suffix != ".desktop" or not path.is_file():
                continue
            parsed = read_desktop_entry(path=path)
            if parsed is not None:
                entry, alias = parsed
                entries[path.stem] = entry
                if alias:
                    aliases[alias] = entry
    for alias, entry in aliases.items():
        entries.setdefault(alias, entry)
    return MappingProxyType(entries)


class DesktopEntryIndex:
    def __init__(self, directories: tuple[Path, ...] | None = None) -> None:
        self._directories = directories if directories is not None else default_directories()
        self._stamp: tuple[tuple[int, int] | None, ...] | None = None
        self._entries: Mapping[str, DesktopEntry] = MappingProxyType({})

    def collect(self) -> CollectorResult[Mapping[str, DesktopEntry]]:
        try:
            stamp = tuple(directory_stamp(path=path) for path in self._directories)
            if stamp != self._stamp:
                entries = build_index(directories=self._directories)
                self._entries, self._stamp = entries, stamp
            return CollectorResult(data=self._entries)
        except Exception as error:
            LOGGER.warning("Desktop entry collection failed: %s", error)
            return CollectorResult(data=MappingProxyType({}), error=str(error))
