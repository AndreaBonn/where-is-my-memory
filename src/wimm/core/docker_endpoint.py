import hashlib
import json
import posixpath
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum

UNIX_PREFIX = "unix://"
RUNTIME_DIR_ENV = "XDG_RUNTIME_DIR"
HOME_ENV = "HOME"
DESKTOP_SOCKET_RELATIVE = ".docker/desktop/docker.sock"
DOCKER_HOST_ENV = "DOCKER_HOST"
DOCKER_CONTEXT_ENV = "DOCKER_CONTEXT"
DEFAULT_CONTEXT_NAME = "default"
DEFAULT_SOCKETS = ("/var/run/docker.sock", "/run/docker.sock")
PODMAN_RUNTIME_SOCKET = "podman/podman.sock"
RUNTIME_DIR_MODE = 0o700
PERMISSION_BITS = 0o7777


class EndpointSource(StrEnum):
    DOCKER_HOST = "DOCKER_HOST"
    DOCKER_CONTEXT = "DOCKER_CONTEXT"
    CONFIG_CONTEXT = "config_context"
    DEFAULT_SOCKET = "default_socket"
    PODMAN_ROOTLESS = "podman_rootless"


class RejectionReason(StrEnum):
    UNSUPPORTED_SCHEME = "unsupported_scheme"
    PATH_NOT_ABSOLUTE = "path_not_absolute"
    LOCATION_NOT_ALLOWED = "location_not_allowed"
    RUNTIME_DIR_NOT_PRIVATE = "runtime_dir_not_private"
    SOCKET_MISSING = "socket_missing"
    NOT_A_SOCKET = "not_a_socket"
    CONTEXT_NOT_FOUND = "context_not_found"
    CONTEXT_INVALID = "context_invalid"


@dataclass(frozen=True, slots=True)
class PathFacts:
    """Filesystem facts about a path, measured by the caller (symlinks followed)."""

    exists: bool
    is_socket: bool
    realpath: str
    owned_by_user: bool
    mode: int


@dataclass(frozen=True, slots=True)
class DockerEndpoint:
    source: EndpointSource
    url: str
    path: str
    realpath: str


@dataclass(frozen=True, slots=True)
class RejectedEndpoint:
    source: EndpointSource
    endpoint: str
    reason: RejectionReason


@dataclass(frozen=True, slots=True)
class EndpointResolution:
    endpoints: tuple[DockerEndpoint, ...]
    rejected: tuple[RejectedEndpoint, ...]


@dataclass(frozen=True, slots=True)
class _Candidate:
    source: EndpointSource
    url: str
    explicit: bool


def context_digest(name: str) -> str:
    """Return the directory name Docker uses for a context's metadata."""
    return hashlib.sha256(name.encode()).hexdigest()


def _parse_json_object(text: str | None) -> dict[str, object] | None:
    try:
        value = json.loads(text) if text is not None else None
    except (ValueError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def _current_context(
    environ: Mapping[str, str], config_json_text: str | None
) -> tuple[EndpointSource, str] | None:
    name = environ.get(DOCKER_CONTEXT_ENV)
    if name:
        return EndpointSource.DOCKER_CONTEXT, name
    config = _parse_json_object(config_json_text)
    current = config.get("currentContext") if config else None
    return (
        (EndpointSource.CONFIG_CONTEXT, current) if isinstance(current, str) and current else None
    )


def _meta_host(meta_text: str) -> str | None:
    meta = _parse_json_object(meta_text)
    endpoints = meta.get("Endpoints") if meta else None
    docker = endpoints.get("docker") if isinstance(endpoints, dict) else None
    host = docker.get("Host") if isinstance(docker, dict) else None
    return host if isinstance(host, str) and host else None


def _context_candidate(
    source: EndpointSource, name: str, read_meta: Callable[[str], str | None]
) -> _Candidate | RejectedEndpoint:
    meta_text = read_meta(context_digest(name))
    if meta_text is None:
        return RejectedEndpoint(
            source=source, endpoint=name, reason=RejectionReason.CONTEXT_NOT_FOUND
        )
    host = _meta_host(meta_text)
    if host is None:
        return RejectedEndpoint(
            source=source, endpoint=name, reason=RejectionReason.CONTEXT_INVALID
        )
    return _Candidate(source=source, url=host, explicit=True)


def _runtime_dir(environ: Mapping[str, str]) -> str | None:
    value = environ.get(RUNTIME_DIR_ENV, "")
    return value if value.startswith("/") and posixpath.normpath(value) == value else None


def _candidates(
    environ: Mapping[str, str],
    config_json_text: str | None,
    read_meta: Callable[[str], str | None],
) -> tuple[list[_Candidate], list[RejectedEndpoint]]:
    found: list[_Candidate] = []
    rejected: list[RejectedEndpoint] = []
    host = environ.get(DOCKER_HOST_ENV)
    if host:
        found.append(_Candidate(source=EndpointSource.DOCKER_HOST, url=host, explicit=True))
    context = _current_context(environ=environ, config_json_text=config_json_text)
    if context is not None and context[1] != DEFAULT_CONTEXT_NAME:
        result = _context_candidate(source=context[0], name=context[1], read_meta=read_meta)
        if isinstance(result, RejectedEndpoint):
            rejected.append(result)
        else:
            found.append(result)
    for default in DEFAULT_SOCKETS:
        found.append(
            _Candidate(
                source=EndpointSource.DEFAULT_SOCKET, url=UNIX_PREFIX + default, explicit=False
            )
        )
    runtime = _runtime_dir(environ=environ)
    if runtime is not None:
        podman = f"{UNIX_PREFIX}{runtime}/{PODMAN_RUNTIME_SOCKET}"
        found.append(_Candidate(source=EndpointSource.PODMAN_ROOTLESS, url=podman, explicit=False))
    return found, rejected


def _socket_path(url: str) -> str | RejectionReason:
    if not url.startswith(UNIX_PREFIX):
        return RejectionReason.UNSUPPORTED_SCHEME
    path = url.removeprefix(UNIX_PREFIX)
    if not path.startswith("/") or "\0" in path or posixpath.normpath(path) != path:
        return RejectionReason.PATH_NOT_ABSOLUTE
    return path


def _under(path: str, directory: str | None) -> bool:
    return directory is not None and path.startswith(directory + "/")


@dataclass(frozen=True, slots=True)
class _Places:
    runtime: str | None
    desktop_socket: str | None
    home: str | None = None


def _places(environ: Mapping[str, str]) -> _Places:
    home = environ.get(HOME_ENV, "")
    valid_home = home.startswith("/") and posixpath.normpath(home) == home and home != "/"
    desktop = posixpath.join(home, DESKTOP_SOCKET_RELATIVE) if valid_home else None
    runtime = _runtime_dir(environ=environ)
    return _Places(runtime=runtime, desktop_socket=desktop, home=home if valid_home else None)


def _desktop_problem(
    path: str, home: str, socket_facts: Callable[[str], PathFacts]
) -> RejectionReason | None:
    """Docker Desktop: the exact socket in the user's home, never through another symlink.

    A home reached through a link (``/home`` on a data disk) is fine: the socket may resolve
    under the real home, and nowhere else.
    """
    facts = socket_facts(path)
    allowed = {path, posixpath.join(socket_facts(home).realpath, DESKTOP_SOCKET_RELATIVE)}
    if facts.exists and (facts.realpath not in allowed or not facts.owned_by_user):
        return RejectionReason.LOCATION_NOT_ALLOWED
    return None


def _runtime_is_private(facts: PathFacts) -> bool:
    return facts.exists and facts.owned_by_user and facts.mode & PERMISSION_BITS == RUNTIME_DIR_MODE


def _location_problem(
    path: str, places: _Places, socket_facts: Callable[[str], PathFacts]
) -> RejectionReason | None:
    """Check the allowed locations (S8) on the lexical path and on the resolved one."""
    runtime = places.runtime
    if places.home is not None and path == places.desktop_socket:
        return _desktop_problem(path=path, home=places.home, socket_facts=socket_facts)
    runtime_facts = socket_facts(runtime) if runtime is not None else None
    runtime_real = runtime_facts.realpath if runtime_facts is not None else None
    if path not in DEFAULT_SOCKETS and not _under(path, runtime):
        return RejectionReason.LOCATION_NOT_ALLOWED
    real = socket_facts(path).realpath
    if real not in DEFAULT_SOCKETS and not _under(real, runtime_real):
        return RejectionReason.LOCATION_NOT_ALLOWED
    needs_private = _under(path, runtime) or _under(real, runtime_real)
    if needs_private and (runtime_facts is None or not _runtime_is_private(runtime_facts)):
        return RejectionReason.RUNTIME_DIR_NOT_PRIVATE
    return None


def _check(
    candidate: _Candidate, places: _Places, socket_facts: Callable[[str], PathFacts]
) -> DockerEndpoint | RejectedEndpoint | None:
    """Return the endpoint, a rejection, or None for an optional socket that is just absent."""

    def reject(reason: RejectionReason) -> RejectedEndpoint:
        return RejectedEndpoint(source=candidate.source, endpoint=candidate.url, reason=reason)

    path = _socket_path(candidate.url)
    if isinstance(path, RejectionReason):
        return reject(path)
    problem = _location_problem(path=path, places=places, socket_facts=socket_facts)
    if problem is not None:
        return reject(problem)
    facts = socket_facts(path)
    if not facts.exists:
        return reject(RejectionReason.SOCKET_MISSING) if candidate.explicit else None
    if not facts.is_socket:
        return reject(RejectionReason.NOT_A_SOCKET)
    return DockerEndpoint(
        source=candidate.source, url=candidate.url, path=path, realpath=facts.realpath
    )


def _evaluate(
    candidates: list[_Candidate],
    places: _Places,
    socket_facts: Callable[[str], PathFacts],
    rejected: list[RejectedEndpoint],
) -> tuple[DockerEndpoint, ...]:
    endpoints: list[DockerEndpoint] = []
    for candidate in candidates:
        outcome = _check(candidate=candidate, places=places, socket_facts=socket_facts)
        if isinstance(outcome, RejectedEndpoint):
            rejected.append(outcome)
        elif outcome is not None and all(e.realpath != outcome.realpath for e in endpoints):
            endpoints.append(outcome)
    return tuple(endpoints)


def resolve_docker_endpoints(
    *,
    environ: Mapping[str, str],
    config_json_text: str | None,
    read_meta: Callable[[str], str | None],
    socket_facts: Callable[[str], PathFacts],
) -> EndpointResolution:
    """List the local engine endpoints (Docker, rootless Podman) that are safe to use.

    Order: DOCKER_HOST, DOCKER_CONTEXT or currentContext, default sockets, rootless Podman.
    Only unix sockets in $XDG_RUNTIME_DIR (user-owned, 0700) or at the default Docker paths
    are accepted; the rest carries a reason code. Same realpath: first one wins.

    `read_meta` takes the sha256 directory name of a context and returns its meta.json text;
    `socket_facts` measures a path on the filesystem. Both are the caller's I/O.
    """
    candidates, rejected = _candidates(
        environ=environ, config_json_text=config_json_text, read_meta=read_meta
    )
    endpoints = _evaluate(
        candidates=candidates,
        places=_places(environ=environ),
        socket_facts=socket_facts,
        rejected=rejected,
    )
    return EndpointResolution(endpoints=endpoints, rejected=tuple(rejected))
