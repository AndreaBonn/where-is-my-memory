from collections.abc import Callable
from dataclasses import replace

from tests.core.disk_helpers import (
    MB,
    cache,
    devdir,
    docker_disk,
    report,
    volume,
)
from tests.ui.disk_view_helpers import MIN_AGE, sections_by_key
from wimm.core.cache_catalog import withheld_kinds
from wimm.core.planning_disk import plan_cache_clean
from wimm.model.actions import ActionRequest
from wimm.model.disk import CacheKind
from wimm.model.enums import ActionKind, TargetId
from wimm.ui.disk_model import DiskRowView, more_text
from wimm.ui.disk_view import build_disk_sections


def test_cache_row_subtitle_carries_the_dialog_consequence() -> None:
    entry = cache(kind=CacheKind.UV, size=3 * MB)
    disk = report(caches=(entry,))
    (row,) = sections_by_key(sections=build_disk_sections(report=disk, min_age_days=MIN_AGE))[
        "caches"
    ].rows
    request = ActionRequest(kind=ActionKind.CACHE_CLEAN, target_id=TargetId(CacheKind.UV.value))
    planned = plan_cache_clean(request=request, report=disk)[0].assessed.consequences[0]
    assert row.consequence
    assert row.consequence == planned


def test_cache_row_without_an_action_has_no_consequence() -> None:
    disk = report(caches=(cache(kind=CacheKind.GO_MOD),))
    sections = build_disk_sections(
        report=disk, min_age_days=MIN_AGE, withheld=frozenset({CacheKind.GO_MOD})
    )
    (row,) = sections_by_key(sections=sections)["caches"].rows
    assert row.action_kind is None
    assert row.consequence == ""


def test_caches_and_trash_are_separate_sections() -> None:
    caches = (cache(kind=CacheKind.UV, size=3 * MB), cache(kind=CacheKind.TRASH, size=9 * MB))
    by_key = sections_by_key(
        sections=build_disk_sections(report=report(caches=caches), min_age_days=MIN_AGE)
    )
    assert [row.title for row in by_key["caches"].rows] == ["uv"]
    assert by_key["caches"].rows[0].risk_text == "Sicuro"
    assert by_key["trash"].rows[0].size_text == "9 MB"
    assert by_key["trash"].rows[0].risk_text == "Pericolo"


def test_every_cache_type_has_a_title_and_the_badge_of_its_own_risk() -> None:
    caches = tuple(
        cache(kind=kind, size=MB, ino=100 + index)
        for index, kind in enumerate(kind for kind in CacheKind if kind is not CacheKind.TRASH)
    )
    by_key = sections_by_key(
        sections=build_disk_sections(report=report(caches=caches), min_age_days=MIN_AGE)
    )
    keys = ("caches", "caches_review", "caches_data")
    rows = {row.title: row for key in keys for row in by_key[key].rows}

    assert len(rows) == len(caches)
    assert (rows["Maven"].risk_text or "").startswith("Attenzione")
    assert (rows["Gradle"].risk_text or "").startswith("Sicuro")
    assert rows["Cargo (pacchetti)"].action_kind is ActionKind.CACHE_CLEAN
    assert rows["Modelli ollama"].risk_text == "Pericolo"
    assert (rows["SDK Android"].risk_text or "").startswith("Attenzione")


def go_row(*, which: Callable[[str], str | None]) -> DiskRowView:
    caches = (cache(kind=CacheKind.GO_MOD, size=7 * MB),)
    sections = build_disk_sections(
        report=report(caches=caches), min_age_days=MIN_AGE, withheld=withheld_kinds(which=which)
    )
    return sections_by_key(sections=sections)["caches"].rows[0]


def test_the_go_module_cache_is_listed_with_its_size_but_without_an_action_without_go() -> None:
    row = go_row(which=lambda _name: None)

    assert (row.title, row.size_text) == ("Go (moduli)", "7 MB")
    assert row.action_kind is None and row.risk_text is None


def test_the_go_module_cache_gets_its_safe_action_when_go_is_on_the_path() -> None:
    row = go_row(which=lambda name: f"/usr/bin/{name}")

    assert (row.title, row.size_text) == ("Go (moduli)", "7 MB")
    assert row.action_kind is ActionKind.CACHE_CLEAN
    assert (row.risk_text or "").startswith("Sicuro")
    assert row.target_id == "go_mod"


def test_empty_devdirs_message_uses_configured_age() -> None:
    by_key = sections_by_key(sections=build_disk_sections(report=report(), min_age_days=45))
    assert by_key["devdirs"].message == (
        "Nessuna cartella di dipendenze più vecchia di 45 giorni nelle radici configurate"
    )
    assert by_key["devdirs"].rows == ()


def test_ten_thousand_devdirs_show_200_rows_and_counter() -> None:
    dirs = tuple(devdir(path=f"/p/{i}/node_modules", size=MB + i) for i in range(10_000))
    by_key = sections_by_key(
        sections=build_disk_sections(report=report(devdirs=dirs), min_age_days=MIN_AGE)
    )
    section = by_key["devdirs"]
    assert len(section.rows) == 200
    assert section.more_text == "e altre 9.800"
    assert section.rows[0].title == "9999 · node_modules"
    assert section.message is None


def test_devdirs_counter_adds_the_collector_truncation() -> None:
    full = report(devdirs=(devdir(path="/p/a/node_modules"),))
    truncated = replace(full, devdirs_truncated=12)
    section = sections_by_key(sections=build_disk_sections(report=truncated, min_age_days=MIN_AGE))[
        "devdirs"
    ]
    assert len(section.rows) == 1
    assert section.more_text == "e altre 12"
    assert "120 giorni" in section.rows[0].subtitle


def test_names_with_markup_characters_stay_raw() -> None:
    docker = docker_disk(volumes=(volume(name="a&b<c>"),))
    rows = sections_by_key(
        sections=build_disk_sections(report=report(docker=docker), min_age_days=MIN_AGE)
    )["volumes"].rows
    assert rows[0].title == "a&b<c>"


def test_more_text_groups_thousands_with_dots() -> None:
    assert more_text(count=9800) == "e altre 9.800"
    assert more_text(count=0) is None
