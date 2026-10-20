"""R1: "Libera spazio" keeps working when the report holds the system ollama store."""

import pytest

from tests.core.disk_helpers import MB, cache, report
from tests.core.ollama_system_helpers import system_entry
from tests.core.test_planning_disk_safe import _path, _plan
from wimm.model.disk import CacheKind
from wimm.model.errors import InvalidRequest


def test_free_safe_skips_the_system_store_and_keeps_the_other_caches() -> None:
    uv = cache(kind=CacheKind.UV, size=MB)
    plan = _plan(disk=report(caches=(system_entry(), uv)))
    assert [_path(step) for step in plan.steps] == [uv.path]


def test_free_safe_with_only_the_system_store_has_nothing_to_free() -> None:
    # The system store is never a step: alone, it leaves the plan empty, as an empty report.
    with pytest.raises(InvalidRequest, match="no executable steps"):
        _plan(disk=report(caches=(system_entry(),)))
