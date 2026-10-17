import logging
import os
import re
import stat
from collections.abc import Callable
from pathlib import Path

from wimm.core import constants as c
from wimm.core.dev_roots import DEV_ROOT_CANDIDATES, select_dev_roots

LOGGER = logging.getLogger(__name__)
USER_DIRS_FILE = Path(".config") / "user-dirs.dirs"
DOCUMENTS_KEY = "XDG_DOCUMENTS_DIR"
HOME_VAR = "$HOME"
GIT_ENTRY = ".git"
GIT_SEARCH_DEPTH = 2
MOUNTINFO_FILE = Path("/proc/self/mountinfo")
MOUNTINFO_SEPARATOR = " - "
MOUNTPOINT_FIELD = 4
_OCTAL_ESCAPE = re.compile(r"\\([0-7]{3})")
_DOCUMENTS_LINE = re.compile(rf'^\s*{DOCUMENTS_KEY}\s*=\s*"([^"\n]*)"\s*$', re.MULTILINE)


def is_safe_candidate(path: Path, home: Path) -> bool:
    """Accept only an existing, non-symlink directory strictly inside ``home``."""
    if not path.is_absolute() or ".." in path.parts or path == home:
        return False
    if not path.is_relative_to(home):
        return False
    try:
        mode = os.lstat(path).st_mode
        # The lexical check above misses a symlinked ancestor that leaves the home.
        real = path.resolve(strict=True)
        real_home = home.resolve(strict=True)
    except FileNotFoundError:
        return False  # the usual case: most candidate names do not exist
    except OSError as error:
        LOGGER.debug("Candidate %s discarded: %s", path, error)
        return False
    return stat.S_ISDIR(mode) and real != real_home and real.is_relative_to(real_home)


def documents_dir(home: Path) -> Path | None:
    """Return the localized documents directory from ``user-dirs.dirs`` if safe."""
    try:
        text = (home / USER_DIRS_FILE).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as error:
        LOGGER.debug("Cannot read user-dirs.dirs: %s", error)
        return None
    match = _DOCUMENTS_LINE.search(text)
    if match is None:
        return None
    value = match.group(1)
    path = home / value[len(HOME_VAR) + 1 :] if value.startswith(f"{HOME_VAR}/") else Path(value)
    if value == HOME_VAR or HOME_VAR in path.as_posix():
        return None
    return path if is_safe_candidate(path=path, home=home) else None


def has_git_repo(path: Path) -> bool:
    """Look for ``.git`` in ``path`` and up to two levels below, never following symlinks."""
    return _scan(path=path, depth=GIT_SEARCH_DEPTH)


def _scan(path: Path, depth: int) -> bool:
    try:
        with os.scandir(path) as entries:
            children = []
            for entry in entries:
                if entry.name == GIT_ENTRY:
                    return True
                if depth > 0 and entry.is_dir(follow_symlinks=False):
                    children.append(entry.path)
    except OSError as error:
        LOGGER.debug("Cannot scan %s: %s", path, error)
        return False
    return any(_scan(path=Path(child), depth=depth - 1) for child in children)


def read_mountinfo() -> str:
    """Return the text of ``/proc/self/mountinfo``, or an empty string if unreadable."""
    try:
        return MOUNTINFO_FILE.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        LOGGER.debug("Cannot read %s: %s", MOUNTINFO_FILE, error)
        return ""


def parse_mountinfo(text: str) -> tuple[tuple[Path, str], ...]:
    """Parse mountinfo into ``(mount point, filesystem type)`` pairs; bad lines are dropped."""
    mounts = []
    for line in text.splitlines():
        head, separator, tail = line.partition(MOUNTINFO_SEPARATOR)
        fields, types = head.split(), tail.split()
        if not separator or len(fields) <= MOUNTPOINT_FIELD or not types:
            continue
        point = _OCTAL_ESCAPE.sub(
            lambda match: chr(int(match.group(1), 8)), fields[MOUNTPOINT_FIELD]
        )
        mounts.append((Path(point), types[0]))
    return tuple(mounts)


def is_network_path(path: Path, mounts: tuple[tuple[Path, str], ...]) -> bool:
    """Tell whether ``path`` lives on a network, FUSE or autofs filesystem.

    The longest mount point containing ``path`` decides, so a local mount nested in a
    network one is local. ``fuseblk`` is a local block device and is not network.
    """
    containing = [(point, kind) for point, kind in mounts if path.is_relative_to(point)]
    if not containing:
        return False
    # max() keeps the first of equals: reversed, a later mount on the same point wins, as
    # it hides the earlier one.
    kind = max(reversed(containing), key=lambda item: len(item[0].parts))[1]
    return kind in c.NETWORK_FSTYPES or kind == "fuse" or kind.startswith("fuse.")


def detect_dev_roots(
    home: Path, read_mounts: Callable[[], str] = read_mountinfo
) -> tuple[Path, ...]:
    """Return the safe candidate directories under ``home`` that contain a repository.

    Candidates on network, FUSE or autofs filesystems are skipped: probing them can block.
    """
    candidates = [home / item.removeprefix("~/") for item in DEV_ROOT_CANDIDATES]
    documents = documents_dir(home=home)
    if documents is not None:
        candidates.append(documents)
    mounts = parse_mountinfo(text=read_mounts())
    safe = (
        str(real)
        for path in candidates
        if is_safe_candidate(path=path, home=home)
        and not is_network_path(path=(real := path.resolve()), mounts=mounts)
    )
    selected = select_dev_roots(candidates=safe, has_repo=lambda item: has_git_repo(Path(item)))
    return tuple(Path(item) for item in selected)
