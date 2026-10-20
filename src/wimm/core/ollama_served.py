"""Which ollama store the client commands reach (T-6.37b, design note section 3).

`ollama list` and `ollama rm` talk to the server that answers on `OLLAMA_HOST`, so what
they show and delete is that server's store. The facts are collected elsewhere and injected.
"""

import ipaddress
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath

from wimm.model.disk import CacheKind

from .cache_catalog import CacheResolution
from .constants import OLLAMA_DEFAULT_PORT

MODELS_VARIABLE = "OLLAMA_MODELS"
HOST_VARIABLE = "OLLAMA_HOST"
HOME_VARIABLE = "HOME"
MAX_PORT = 65535
# Where ollama keeps a user's models when OLLAMA_MODELS is not set.
DEFAULT_MODELS_DIR = (".ollama", "models")
LOCAL_NAMES = frozenset({"", "localhost"})
_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://")
_BRACKETED = re.compile(r"^\[([^\]]*)\]")


@dataclass(frozen=True, slots=True)
class Endpoint:
    name: str
    port: int


class ServedStore(Enum):
    NONE = "none"  # S0: no server, the client commands fail
    USER_HOME = "user_home"  # S1: the user's server on the home store
    USER_OTHER = "user_other"  # S1': the user's server on another store, or unreadable
    SYSTEM = "system"  # S2: one server of another user
    AMBIGUOUS = "ambiguous"  # S3: two or more servers, or a remote host


@dataclass(frozen=True, slots=True)
class ServeProcess:
    """An `ollama serve` process; `environ` is None when it could not be read."""

    uid: int
    environ: Mapping[str, str] | None


@dataclass(frozen=True, slots=True)
class ServedFacts:
    """What the collector saw: the servers, who runs wimm, and where the home store is."""

    processes: Sequence[ServeProcess]
    current_uid: int
    ollama_host: str | None
    home_store: str
    default_models: str
    # `ollama` processes whose command line could not be read: they may be servers.
    unreadable_ollama: int = 0


def _endpoint(*, host: str | None) -> Endpoint | None:
    """(name, port) of an OLLAMA_HOST value; None when it has userinfo or a broken port."""
    rest = _SCHEME.sub("", (host or "").strip()).split("/", 1)[0]
    if "@" in rest:
        return None
    bracketed = _BRACKETED.match(rest)
    if bracketed:
        name, port_text = bracketed.group(1), rest[bracketed.end() :].removeprefix(":")
    elif rest.count(":") > 1:
        name, port_text = rest, ""
    else:
        name, _, port_text = rest.partition(":")
    if not port_text:
        return Endpoint(name=name, port=OLLAMA_DEFAULT_PORT)
    if not port_text.isascii() or not port_text.isdigit() or not 0 < int(port_text) <= MAX_PORT:
        return None
    return Endpoint(name=name, port=int(port_text))


def _is_local(*, name: str) -> bool:
    if name in LOCAL_NAMES:
        return True
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        return False
    return address.is_loopback or address.is_unspecified


def _models_folder(*, environ: Mapping[str, str], facts: ServedFacts) -> str | None:
    """Where the user's server keeps its models; None for a value that is not absolute."""
    explicit = environ.get(MODELS_VARIABLE)
    if explicit:
        return explicit if PurePosixPath(explicit).is_absolute() else None
    home = environ.get(HOME_VARIABLE)
    if not home:
        return facts.default_models
    return default_models_path(home=Path(home)) if PurePosixPath(home).is_absolute() else None


def _user_server_store(
    *, process: ServeProcess, facts: ServedFacts, realpath: Callable[[str], str]
) -> ServedStore:
    if process.environ is None:
        return ServedStore.USER_OTHER
    models = _models_folder(environ=process.environ, facts=facts)
    if models is None:
        return ServedStore.USER_OTHER
    same = realpath(models) == realpath(facts.home_store)
    return ServedStore.USER_HOME if same else ServedStore.USER_OTHER


def _same_port(*, process: ServeProcess, client: Endpoint) -> bool:
    """The user's own server listens where the client talks; an unreadable one is not checked."""
    if process.environ is None:
        return True
    server = _endpoint(host=process.environ.get(HOST_VARIABLE))
    return server is not None and server.port == client.port


def served_store(*, facts: ServedFacts, realpath: Callable[[str], str]) -> ServedStore:
    """Classify the situation S0-S3; `realpath` resolves links so two spellings compare equal."""
    client = _endpoint(host=facts.ollama_host)
    if client is None or not _is_local(name=client.name):
        return ServedStore.AMBIGUOUS
    if len(facts.processes) > 1 or facts.unreadable_ollama > 0:
        return ServedStore.AMBIGUOUS
    if not facts.processes:
        return ServedStore.NONE
    (process,) = facts.processes
    if process.uid != facts.current_uid:
        # The environ of another user's server is unreadable: only the default port is safe.
        default = client.port == OLLAMA_DEFAULT_PORT
        return ServedStore.SYSTEM if default else ServedStore.AMBIGUOUS
    if not _same_port(process=process, client=client):
        return ServedStore.AMBIGUOUS
    return _user_server_store(process=process, facts=facts, realpath=realpath)


def default_models_path(*, home: Path) -> str:
    """The store an ollama server of this user uses when OLLAMA_MODELS is not set."""
    return str(home.joinpath(*DEFAULT_MODELS_DIR))


def home_store_path(*, table: CacheResolution, home: Path) -> str:
    """The home store wimm measures: the OLLAMA cache of the start-up table, or the default."""
    for cache in table.caches:
        if cache.kind is CacheKind.OLLAMA:
            return str(cache.path)
    return default_models_path(home=home)
