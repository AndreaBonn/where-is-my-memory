"""T-6.39: ollama item rows follow the server situation S0-S3 (design note L5, D1)."""

from dataclasses import replace

import pytest

from tests.core.disk_helpers import MB, report
from tests.core.ollama_system_helpers import system_entry
from wimm.core.ollama_served import ServedStore
from wimm.model.cache_items import CacheItem
from wimm.model.disk import CacheEntry, CacheKind
from wimm.model.enums import ActionKind, CacheItemKind
from wimm.ui.disk_items import item_rows
from wimm.ui.disk_model import DiskRowView
from wimm.ui.disk_view import build_disk_sections

HOME_STORE = "/home/u/.ollama/models"
REASONS = {
    ServedStore.NONE: "Avvia ollama per rimuovere un modello",
    ServedStore.USER_OTHER: "Il server ollama attivo usa un'altra cartella di modelli",
    ServedStore.SYSTEM: "Il server ollama attivo è quello di sistema e non vede questi modelli",
}
NOT_OFFERED = [ServedStore.NONE, ServedStore.USER_OTHER, ServedStore.SYSTEM, ServedStore.AMBIGUOUS]


def _home_entry(*, name: str = "gemma3:4b") -> CacheEntry:
    item = CacheItem(
        id=name,
        title=name,
        path=f"{HOME_STORE}/manifests/{name}",
        size=MB,
        st_ino=5,
        st_dev=2049,
        kind=CacheItemKind.OLLAMA_MODEL,
    )
    return CacheEntry(
        kind=CacheKind.OLLAMA, path=HOME_STORE, size=MB, st_ino=4, st_dev=2049, items=(item,)
    )


def _row(*, entry: CacheEntry, served: ServedStore | None) -> DiskRowView:
    (row,) = item_rows(entry=entry, served=served).rows
    return row


def _cache_row(*, entry: CacheEntry, served: str) -> DiskRowView:
    full = replace(report(caches=(entry,)), ollama_served=served)
    sections = build_disk_sections(report=full, min_age_days=30)
    rows = [row for section in sections for row in section.rows if row.items]
    assert len(rows) == 1
    return rows[0]


def test_a_home_model_is_offered_only_when_the_users_server_serves_the_home_store() -> None:
    row = _row(entry=_home_entry(), served=ServedStore.USER_HOME)
    assert row.action_kind is ActionKind.CACHE_ITEM_REMOVE
    assert row.target_id == "ollama:gemma3:4b"
    assert row.consequence
    assert row.note == ""


@pytest.mark.parametrize("served", NOT_OFFERED)
def test_a_home_model_is_not_offered_in_any_other_situation(served: ServedStore) -> None:
    row = _row(entry=_home_entry(), served=served)
    assert row.action_kind is None
    assert row.target_id is None
    assert row.consequence == ""
    assert row.note != ""


@pytest.mark.parametrize("served", list(REASONS))
def test_the_reason_names_the_situation(served: ServedStore) -> None:
    assert _row(entry=_home_entry(), served=served).note == REASONS[served]


def test_the_ambiguous_situation_says_it_cannot_tell_which_server_answers() -> None:
    note = _row(entry=_home_entry(), served=ServedStore.AMBIGUOUS).note
    assert "più di un server" in note
    assert note not in REASONS.values()


def test_an_unknown_situation_offers_nothing_and_says_what_the_ambiguous_one_says() -> None:
    unknown = _row(entry=_home_entry(), served=None)
    assert unknown.action_kind is None
    assert unknown.note == _row(entry=_home_entry(), served=ServedStore.AMBIGUOUS).note


@pytest.mark.parametrize("name", ["-rf:x", "gemma3", "a b:1", "x:1\x1b"])
def test_a_home_model_with_an_invalid_name_never_offers_the_action(name: str) -> None:
    for served in ServedStore:
        row = _row(entry=_home_entry(name=name), served=served)
        assert row.action_kind is None
        assert row.title == name  # still shown: its bytes count


def test_the_system_models_are_offered_only_in_situation_s2() -> None:
    row = _row(entry=system_entry(), served=ServedStore.SYSTEM)
    assert row.action_kind is ActionKind.CACHE_ITEM_REMOVE
    assert row.target_id == "ollama_system:gemma3:4b"
    assert row.note == ""


@pytest.mark.parametrize("served", [s for s in NOT_OFFERED if s is not ServedStore.SYSTEM])
def test_the_system_models_are_not_offered_when_the_server_is_not_the_system_one(
    served: ServedStore,
) -> None:
    row = _row(entry=system_entry(), served=served)
    assert row.action_kind is None
    assert row.note != ""


def test_the_system_entry_row_has_its_title_the_estimate_subtitle_and_no_cache_action() -> None:
    row = _cache_row(entry=system_entry(), served=ServedStore.SYSTEM.value)
    assert row.title == "Modelli ollama (sistema)"
    assert row.subtitle == "dimensioni stimate da ollama"
    assert row.action_kind is None
    (item,) = row.items
    assert item.action_kind is ActionKind.CACHE_ITEM_REMOVE


def test_a_home_entry_row_keeps_its_path_and_gets_the_report_situation() -> None:
    row = _cache_row(entry=_home_entry(), served=ServedStore.USER_HOME.value)
    assert row.subtitle == HOME_STORE
    assert row.action_kind is None
    assert row.note == "Ferma ollama per pulire tutta la cache"
    assert row.items[0].action_kind is ActionKind.CACHE_ITEM_REMOVE
    refused = _cache_row(entry=_home_entry(), served=ServedStore.NONE.value)
    assert refused.action_kind is ActionKind.CACHE_CLEAN
    assert refused.items[0].action_kind is None
    assert refused.items[0].note == REASONS[ServedStore.NONE]


@pytest.mark.parametrize("served", ["", "nonsense"])
def test_a_report_without_the_situation_or_with_a_wrong_one_offers_no_ollama_removal(
    served: str,
) -> None:
    row = _cache_row(entry=_home_entry(), served=served)
    assert row.items[0].action_kind is None
