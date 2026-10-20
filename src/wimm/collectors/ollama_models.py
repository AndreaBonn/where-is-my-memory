"""The models of a system-wide ollama install, listed by `ollama list` (T-6.37c, design note L5).

The entry exists only in situation S2: one server of another user answers the client. In
every other case, and whenever the listing cannot be trusted, there is no entry and one
WARNING says why: an invented or partial list would be shown as the user's disk.
"""

import logging
import os
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import psutil

from wimm.collectors.ollama_command import (
    CommandOutput,
    CommandRunner,
    OllamaCommandError,
    run_command,
)
from wimm.collectors.ollama_processes import ServeReader, collect_serve_processes
from wimm.core.cache_catalog import CacheResolution
from wimm.core.constants import (
    OLLAMA_COMMAND_ENV_KEYS,
    OLLAMA_LIST_COMMAND,
    OLLAMA_LIST_TIMEOUT_S,
    OLLAMA_NAME,
    OLLAMA_SYSTEM_PATH,
)
from wimm.core.ollama_list import ListedModel, parse_ollama_list
from wimm.core.ollama_served import (
    ServedFacts,
    ServedStore,
    default_models_path,
    home_store_path,
    served_store,
)
from wimm.core.terminal_text import printable
from wimm.model import CacheEntry, CacheItem, CacheItemKind, CacheKind

LOGGER = logging.getLogger(__name__)


def _item(*, model: ListedModel) -> CacheItem:
    return CacheItem(
        id=model.name,
        title=model.name,
        path=f"ollama:{model.name}",
        size=model.size,
        st_ino=0,
        st_dev=0,
        kind=CacheItemKind.OLLAMA_MODEL,
        model_id=model.model_id,
    )


def _entry(*, models: tuple[ListedModel, ...]) -> CacheEntry:
    return CacheEntry(
        kind=CacheKind.OLLAMA_SYSTEM,
        path=OLLAMA_SYSTEM_PATH,
        size=sum(model.size for model in models),
        st_ino=0,
        st_dev=0,
        items=tuple(_item(model=model) for model in models),
    )


def _home_names(*, caches: tuple[CacheEntry, ...]) -> frozenset[str]:
    return frozenset(
        item.id for entry in caches if entry.kind is CacheKind.OLLAMA for item in entry.items
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class OllamaSystemSource:
    """Everything the collector touches, injected: tool lookup, command, processes, uid, env."""

    which: Callable[[str], str | None]
    runner: CommandRunner
    reader: ServeReader
    current_uid: int
    environ: Mapping[str, str]
    realpath: Callable[[str], str] = os.path.realpath

    def collect(
        self, *, home: Path, table: CacheResolution, caches: tuple[CacheEntry, ...]
    ) -> CacheEntry | None:
        """The system store entry, or None with a WARNING when it cannot be shown."""
        tool = self._tool()
        if tool is None:
            LOGGER.warning("System ollama store skipped: the ollama tool was not found")
            return None
        situation = self._situation(home=home, table=table)
        if situation is not ServedStore.SYSTEM:
            LOGGER.warning("System ollama store skipped: server situation is %s", situation.value)
            return None
        models = self._list(tool=tool)
        if models is None:
            return None
        if models and {model.name for model in models} == _home_names(caches=caches):
            LOGGER.warning("System ollama store skipped: same models as the home store")
            return None
        return _entry(models=models)

    def _tool(self) -> str | None:
        found = self.which(OLLAMA_NAME)
        return found if found and os.path.isabs(found) else None

    def _situation(self, *, home: Path, table: CacheResolution) -> ServedStore:
        facts = ServedFacts(
            processes=collect_serve_processes(reader=self.reader, current_uid=self.current_uid),
            current_uid=self.current_uid,
            ollama_host=self.environ.get("OLLAMA_HOST"),
            home_store=home_store_path(table=table, home=home),
            default_models=default_models_path(home=home),
        )
        return served_store(facts=facts, realpath=self.realpath)

    def _list(self, *, tool: str) -> tuple[ListedModel, ...] | None:
        env = {key: self.environ[key] for key in OLLAMA_COMMAND_ENV_KEYS if key in self.environ}
        try:
            result = self.runner(
                argv=[tool, OLLAMA_LIST_COMMAND], timeout_s=OLLAMA_LIST_TIMEOUT_S, env=env
            )
        except OllamaCommandError as error:
            LOGGER.warning("System ollama store skipped: %s", error)
            return None
        return _parse(result=result)


def _parse(*, result: CommandOutput) -> tuple[ListedModel, ...] | None:
    if result.returncode:
        LOGGER.warning(
            "System ollama store skipped: ollama list exit code %d: %s",
            result.returncode,
            printable(text=result.stderr or result.stdout),
        )
        return None
    models = parse_ollama_list(text=result.stdout)
    if not models:
        reason = "the output has an unknown format" if models is None else "no model is listed"
        LOGGER.warning("System ollama store skipped: %s", reason)
        return None
    return models


def real_ollama_source() -> OllamaSystemSource:
    """The source for the running application: PATH lookup, subprocess, psutil, live env."""
    return OllamaSystemSource(
        which=shutil.which,
        runner=run_command,
        reader=psutil,
        current_uid=os.getuid(),
        environ=os.environ,
    )
