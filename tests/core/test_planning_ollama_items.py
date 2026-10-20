"""T-6.38a: planning the removal of an ollama model, from the home store or the system one."""

from dataclasses import replace

import pytest

from wimm.model import CacheEntry, CacheItem, CacheItemKind, CacheKind, ItemFingerprint
from wimm.model.actions import Plan
from wimm.model.enums import ActionKind, Risk
from wimm.model.errors import InvalidRequest
from wimm.model.served_fingerprint import ServedModelFingerprint

from .disk_helpers import MB, report
from .ollama_system_helpers import MODEL_ID, model, system_entry
from .planning_disk_helpers import _plan

STORE = "/home/u/.ollama/models"
MANIFEST = f"{STORE}/manifests/registry.ollama.ai/library/gemma3/4b"


def _home_item(*, name: str = "gemma3:4b") -> CacheItem:
    return CacheItem(
        id=name,
        title=name,
        path=MANIFEST,
        size=3 * MB,
        st_ino=7,
        st_dev=2049,
        kind=CacheItemKind.OLLAMA_MODEL,
    )


def _home_entry(*, item: CacheItem) -> CacheEntry:
    return CacheEntry(
        kind=CacheKind.OLLAMA, path=STORE, size=5 * MB, st_ino=31, st_dev=2049, items=(item,)
    )


def _remove(*, entries: tuple[CacheEntry, ...], target: str) -> Plan:
    return _plan(kind=ActionKind.CACHE_ITEM_REMOVE, disk=report(caches=entries), target=target)


def test_a_system_model_plans_one_danger_step_with_the_served_identity() -> None:
    plan = _remove(entries=(system_entry(size=MB),), target="ollama_system:gemma3:4b")

    assert len(plan.steps) == 1
    step = plan.steps[0]
    assert step.fingerprint == ServedModelFingerprint(name="gemma3:4b", model_id=MODEL_ID)
    assert step.risk is Risk.DANGER
    assert plan.confirm_phrase == "gemma3:4b"
    assert plan.estimated_reclaim_disk == MB


def test_the_two_stores_with_the_same_name_resolve_to_their_own_item() -> None:
    entries = (_home_entry(item=_home_item()), system_entry(size=MB))

    home = _remove(entries=entries, target="ollama:gemma3:4b")
    system = _remove(entries=entries, target="ollama_system:gemma3:4b")

    assert home.steps[0].fingerprint == ItemFingerprint(
        realpath=MANIFEST, st_ino=7, st_dev=2049, blobs=()
    )
    assert isinstance(system.steps[0].fingerprint, ServedModelFingerprint)
    assert home.estimated_reclaim_disk == 3 * MB
    assert system.estimated_reclaim_disk == MB


@pytest.mark.parametrize("name", ["-rf:x", "a b:c", "gemma3", "x:\x1b[2K"])
def test_a_home_model_with_a_bad_name_is_not_planned(name: str) -> None:
    entry = _home_entry(item=_home_item(name=name))
    with pytest.raises(InvalidRequest):
        _remove(entries=(entry,), target=f"ollama:{name}")
    good = _home_entry(item=_home_item())
    assert _remove(entries=(good,), target="ollama:gemma3:4b").steps


@pytest.mark.parametrize("name", ["-rf:x", "a b:c", "gemma3", "x:\x1b[2K"])
def test_a_system_model_with_a_bad_name_is_not_planned(name: str) -> None:
    bad = replace(model(), id=name, title=name, path=f"ollama:{name}")
    entry = system_entry(items=(bad,), size=MB)
    with pytest.raises(InvalidRequest):
        _remove(entries=(entry,), target=f"ollama_system:{name}")
    assert _remove(entries=(system_entry(),), target="ollama_system:gemma3:4b").steps


def test_the_whole_system_store_is_never_cleaned_but_the_home_one_still_is() -> None:
    entries = (_home_entry(item=_home_item()), system_entry(size=MB))

    with pytest.raises(InvalidRequest):
        _plan(kind=ActionKind.CACHE_CLEAN, disk=report(caches=entries), target="ollama_system")

    plan = _plan(kind=ActionKind.CACHE_CLEAN, disk=report(caches=entries), target="ollama")
    assert plan.steps[0].kind is ActionKind.CACHE_CLEAN
    assert plan.risk is Risk.DANGER
