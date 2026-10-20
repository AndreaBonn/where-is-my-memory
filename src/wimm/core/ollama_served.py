"""Which ollama store the client commands reach (T-6.37b, design note section 3).

`ollama list` and `ollama rm` talk to the server that answers on `OLLAMA_HOST`, so what
they show and delete is that server's store. The facts are collected elsewhere and injected.
"""

import ipaddress
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from wimm.model.disk import CacheKind

from .cache_catalog import CacheResolution

MODELS_VARIABLE = "OLLAMA_MODELS"
# Where ollama keeps a user's models when OLLAMA_MODELS is not set.
DEFAULT_MODELS_DIR = (".ollama", "models")
LOCAL_NAMES = frozenset({"", "localhost"})
_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://")
_BRACKETED = re.compile(r"^\[([^\]]*)\]")


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


def _host_name(*, host: str) -> str:
    rest = _SCHEME.sub("", host.strip()).split("/", 1)[0]
    bracketed = _BRACKETED.match(rest)
    if bracketed:
        return bracketed.group(1)
    return rest if rest.count(":") > 1 else rest.split(":", 1)[0]


def _is_local(*, host: str | None) -> bool:
    name = _host_name(host=host or "")
    if name in LOCAL_NAMES:
        return True
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        return False
    return address.is_loopback or address.is_unspecified


def _user_server_store(
    *, process: ServeProcess, facts: ServedFacts, realpath: Callable[[str], str]
) -> ServedStore:
    if process.environ is None:
        return ServedStore.USER_OTHER
    models = process.environ.get(MODELS_VARIABLE) or facts.default_models
    same = realpath(models) == realpath(facts.home_store)
    return ServedStore.USER_HOME if same else ServedStore.USER_OTHER


def served_store(*, facts: ServedFacts, realpath: Callable[[str], str]) -> ServedStore:
    """Classify the situation S0-S3; `realpath` resolves links so two spellings compare equal."""
    if not _is_local(host=facts.ollama_host) or len(facts.processes) > 1:
        return ServedStore.AMBIGUOUS
    if not facts.processes:
        return ServedStore.NONE
    (process,) = facts.processes
    if process.uid != facts.current_uid:
        return ServedStore.SYSTEM
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
