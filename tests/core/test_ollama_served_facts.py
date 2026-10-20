"""Where the home ollama store is, worked out once for the scan and for the executor."""

from pathlib import Path

import pytest

from wimm.core.cache_catalog import CacheAccess, CacheResolution, ResolvedCache
from wimm.core.ollama_served import default_models_path, home_store_path
from wimm.model.disk import CacheKind

HOME = Path("/home/u")
CLEANABLE = CacheAccess.CLEANABLE


def _table(*, ollama: Path | None) -> CacheResolution:
    uv = ResolvedCache(
        kind=CacheKind.UV, path=HOME / ".cache/uv", redirected=False, access=CLEANABLE
    )
    caches: tuple[ResolvedCache, ...] = (uv,)
    if ollama is not None:
        caches += (
            ResolvedCache(kind=CacheKind.OLLAMA, path=ollama, redirected=True, access=CLEANABLE),
        )
    return CacheResolution(caches=caches, rejected=())


@pytest.mark.parametrize("ollama", [Path("/data/models"), None])
def test_home_store_path_takes_the_table_entry_or_the_default(ollama: Path | None) -> None:
    found = home_store_path(table=_table(ollama=ollama), home=HOME)
    assert found == str(ollama or HOME / ".ollama/models")


def test_default_models_path_is_under_the_home() -> None:
    assert default_models_path(home=HOME) == "/home/u/.ollama/models"
