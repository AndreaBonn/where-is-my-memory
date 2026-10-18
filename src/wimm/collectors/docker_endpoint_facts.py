import logging
import os
import re
import stat
from collections.abc import Mapping
from pathlib import Path

from wimm.core.docker_endpoint import (
    PERMISSION_BITS,
    EndpointResolution,
    PathFacts,
    resolve_docker_endpoints,
)

LOGGER = logging.getLogger(__name__)
MAX_DOCKER_FILE_BYTES = 64 * 1024
DOCKER_DIR = ".docker"
CONFIG_FILE = "config.json"
CONTEXT_META_DIR = "contexts/meta"
META_FILE = "meta.json"
DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}")
OPEN_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK


def read_bounded_text(path: Path, limit: int) -> str | None:
    """Read a small regular file without following a symlink at the final component.

    Parameters
    ----------
    path : Path
        File to read.
    limit : int
        Maximum size in bytes; a larger file is refused, not truncated.

    Returns
    -------
    str | None
        UTF-8 text, or None when the file is missing, not regular, too big or undecodable.
    """
    try:
        descriptor = os.open(path, OPEN_FLAGS)
    except OSError as error:
        LOGGER.debug("Cannot open %s: %s", path, error)
        return None
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return None
        data = os.read(descriptor, limit + 1)
        return data.decode() if len(data) <= limit else None
    except (OSError, UnicodeDecodeError) as error:
        LOGGER.debug("Cannot read %s: %s", path, error)
        return None
    finally:
        os.close(descriptor)


def read_docker_config(home: Path) -> str | None:
    """Return the text of ~/.docker/config.json, if usable."""
    return read_bounded_text(path=home / DOCKER_DIR / CONFIG_FILE, limit=MAX_DOCKER_FILE_BYTES)


def read_context_meta(home: Path, digest: str) -> str | None:
    """Return the meta.json of the context stored under the given sha256 directory name."""
    if DIGEST_PATTERN.fullmatch(digest) is None:
        return None
    path = home / DOCKER_DIR / CONTEXT_META_DIR / digest / META_FILE
    return read_bounded_text(path=path, limit=MAX_DOCKER_FILE_BYTES)


def stat_path(path: str) -> PathFacts:
    """Measure the facts the endpoint resolver needs about a path (symlinks followed)."""
    real = os.path.realpath(path)
    try:
        info = os.stat(path)
    except FileNotFoundError:
        return PathFacts(exists=False, is_socket=False, realpath=real, owned_by_user=False, mode=0)
    except OSError as error:
        LOGGER.debug("Cannot stat %s: %s", path, error)
        return PathFacts(exists=True, is_socket=False, realpath=real, owned_by_user=False, mode=0)
    return PathFacts(
        exists=True,
        is_socket=stat.S_ISSOCK(info.st_mode),
        realpath=real,
        owned_by_user=info.st_uid == os.getuid(),
        mode=info.st_mode & PERMISSION_BITS,
    )


def resolve_local_docker_endpoints(environ: Mapping[str, str], home: Path) -> EndpointResolution:
    """Resolve the local engine endpoints from the real filesystem and environment.

    ``home`` also overrides ``HOME`` in ``environ``, so the config and the Docker Desktop
    socket are always looked up in the same home.
    """
    return resolve_docker_endpoints(
        environ={**environ, "HOME": str(home)},
        config_json_text=read_docker_config(home=home),
        read_meta=lambda digest: read_context_meta(home=home, digest=digest),
        socket_facts=stat_path,
    )
