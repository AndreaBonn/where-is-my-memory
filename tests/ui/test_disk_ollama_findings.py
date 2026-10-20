from dataclasses import replace

import pytest

from tests.core.disk_helpers import report
from tests.core.ollama_system_helpers import MODEL_ID, model, system_entry
from wimm.core.ollama_served import ServedStore
from wimm.model.disk import CacheEntry, CacheKind
from wimm.model.enums import ActionKind
from wimm.ui.disk_items import item_rows
from wimm.ui.disk_view import build_disk_sections

HOME_STORE = "/home/u/.ollama/models"
BLOCKED = ["", "unknown", *(s.value for s in ServedStore if s is not ServedStore.NONE)]


def home_entry(*, with_items: bool = True) -> CacheEntry:
    item = replace(model(), path=f"{HOME_STORE}/manifests/gemma3:4b")
    return replace(
        system_entry(items=(item,) if with_items else ()),
        kind=CacheKind.OLLAMA,
        path=HOME_STORE,
    )


@pytest.mark.parametrize("served", BLOCKED)
@pytest.mark.parametrize("with_items", [True, False])
def test_home_clean_is_refused_with_a_reason_and_stays_in_danger(
    served: str, with_items: bool
) -> None:
    entry = home_entry(with_items=with_items)
    disk = replace(report(caches=(entry,)), ollama_served=served)
    sections = build_disk_sections(report=disk, min_age_days=30, withheld=frozenset())
    section = next(s for s in sections if any(r.subtitle == HOME_STORE for r in s.rows))
    (row,) = section.rows
    assert row.action_kind is None
    assert row.note == "Ferma ollama per pulire tutta la cache"
    assert row.consequence == ""
    assert (section.key, section.title, section.tier) == (
        "caches_data",
        "Modelli ed emulatori",
        "data",
    )
    allowed = replace(disk, ollama_served=ServedStore.NONE.value)
    positive = build_disk_sections(report=allowed, min_age_days=30, withheld=frozenset())
    clean = next(r for s in positive for r in s.rows if r.subtitle == HOME_STORE)
    assert clean.action_kind is ActionKind.CACHE_CLEAN
    assert clean.note == ""
    assert clean.consequence


def test_system_model_subtitle_identifies_the_model_and_home_keeps_its_path() -> None:
    system = item_rows(entry=system_entry(), served=ServedStore.SYSTEM).rows[0]
    assert system.subtitle != model().path
    assert system.subtitle == f"ID {MODEL_ID}"
    home = item_rows(entry=home_entry(), served=ServedStore.USER_HOME).rows[0]
    assert home.subtitle == f"{HOME_STORE}/manifests/gemma3:4b"
