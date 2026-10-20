"""Fakes for the system ollama collector: no real ollama and no real /proc (T-6.37c)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from wimm.collectors.ollama_command import CommandOutput, OllamaCommandError
from wimm.collectors.ollama_models import OllamaScan, OllamaSystemSource
from wimm.core.cache_catalog import CacheAccess, CacheResolution, ResolvedCache
from wimm.core.constants import OLLAMA_NAME
from wimm.model import CacheEntry, CacheItem, CacheItemKind, CacheKind

LIST_FIXTURE = Path(__file__).parents[1] / "fixtures" / "ollama" / "list_0_18_0.txt"
TOOL = "/usr/local/bin/ollama"
CURRENT_UID = 1000
SERVICE_UID = 997
HOME = Path("/home/u")
HOME_STORE = "/home/u/.ollama/models"
CONNECT_ERROR = "Error: could not connect to ollama server, run 'ollama serve' to start it"


def listing() -> str:
    return LIST_FIXTURE.read_text(encoding="utf-8")


@dataclass(frozen=True)
class _Uids:
    real: int


@dataclass
class FakeProcess:
    """What psutil gives: `info` and `environ()`; `environ_error` makes it unreadable."""

    uid: int
    cmdline: list[str] | None = field(default_factory=lambda: [TOOL, "serve"])
    environ_value: Mapping[str, str] = field(default_factory=dict)
    environ_error: Exception | None = None
    environ_calls: int = 0
    pid: int = 2600
    name: str | None = OLLAMA_NAME
    uids_denied: bool = False

    @property
    def info(self) -> dict[str, Any]:
        """Like psutil's `process_iter(attrs)`: an attribute it was denied is None."""
        uids = None if self.uids_denied else _Uids(real=self.uid)
        return {"name": self.name, "cmdline": self.cmdline, "uids": uids}

    def environ(self) -> Mapping[str, str]:
        self.environ_calls += 1
        if self.environ_error is not None:
            raise self.environ_error
        return self.environ_value


class FakeReader:
    def __init__(self, *processes: FakeProcess) -> None:
        self.processes = processes

    def process_iter(self, attrs: list[str]) -> list[FakeProcess]:
        return list(self.processes)


class FakeRunner:
    """Records every call; answers with `output` or raises `error`."""

    def __init__(
        self, *, output: CommandOutput | None = None, error: OllamaCommandError | None = None
    ) -> None:
        self.output = output or CommandOutput(returncode=0, stdout=listing(), stderr="")
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self, *, argv: Sequence[str], timeout_s: float, env: Mapping[str, str]
    ) -> CommandOutput:
        self.calls.append({"argv": list(argv), "timeout_s": timeout_s, "env": dict(env)})
        if self.error is not None:
            raise self.error
        return self.output


def source(
    *,
    runner: FakeRunner,
    reader: FakeReader | None = None,
    tool: str | None = TOOL,
    environ: Mapping[str, str] | None = None,
) -> OllamaSystemSource:
    return OllamaSystemSource(
        which=lambda name: tool,
        runner=runner,
        reader=reader or FakeReader(FakeProcess(uid=SERVICE_UID)),
        current_uid=CURRENT_UID,
        environ={"PATH": "/usr/bin"} if environ is None else environ,
        realpath=lambda path: path,
    )


def table(*, store: str | None = None) -> CacheResolution:
    """A start-up table; with `store` it holds the ollama cache at that path."""
    caches: tuple[ResolvedCache, ...] = ()
    if store is not None:
        caches = (
            ResolvedCache(
                kind=CacheKind.OLLAMA,
                path=Path(store),
                redirected=False,
                access=CacheAccess.CLEANABLE,
            ),
        )
    return CacheResolution(caches=caches, rejected=())


def home_entry(*names: str) -> CacheEntry:
    """The home ollama cache with one item per name."""
    items = tuple(
        CacheItem(
            id=name,
            title=name,
            path=f"{HOME_STORE}/manifests/{name}",
            size=10,
            st_ino=1,
            st_dev=1,
            kind=CacheItemKind.OLLAMA_MODEL,
        )
        for name in names
    )
    return CacheEntry(
        kind=CacheKind.OLLAMA,
        path=HOME_STORE,
        size=10 * len(names),
        st_ino=1,
        st_dev=1,
        items=items,
    )


def scan(
    *,
    runner: FakeRunner,
    caches: tuple[CacheEntry, ...] = (),
    store: str | None = None,
    **options: Any,
) -> OllamaScan:
    return source(runner=runner, **options).collect(
        home=HOME, table=table(store=store), caches=caches
    )


def collect(
    *,
    runner: FakeRunner,
    caches: tuple[CacheEntry, ...] = (),
    store: str | None = None,
    **options: Any,
) -> CacheEntry | None:
    return scan(runner=runner, caches=caches, store=store, **options).entry
