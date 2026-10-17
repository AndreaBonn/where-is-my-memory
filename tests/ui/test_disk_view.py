from dataclasses import replace
from datetime import datetime, timedelta, timezone

from tests.core.disk_helpers import (
    MB,
    cache,
    devdir,
    docker_disk,
    image,
    report,
    stopped,
    volume,
)
from wimm.model.disk import CacheKind, DockerDisk
from wimm.model.enums import ActionKind
from wimm.model.snapshot import DockerStatus
from wimm.ui.disk_model import DiskSectionView, more_text
from wimm.ui.disk_texts import SECTION_DESCRIPTIONS, disk_headline
from wimm.ui.disk_view import build_disk_sections, last_scan_text

MIN_AGE = 90
LOCAL = timezone(timedelta(hours=2))


def sections_by_key(*, sections: tuple[DiskSectionView, ...]) -> dict[str, DiskSectionView]:
    return {section.key: section for section in sections}


def test_no_report_has_no_sections() -> None:
    assert build_disk_sections(report=None, min_age_days=MIN_AGE) == ()


def test_last_scan_text_uses_local_time_and_none_text() -> None:
    now = datetime(2026, 10, 16, 15, 0, tzinfo=LOCAL)
    scanned = report().scanned_at
    assert last_scan_text(report=report(), now=now) == "Ultimo controllo alle 14:00"
    assert scanned.hour == 12
    assert last_scan_text(report=None, now=now) == "Nessun controllo ancora"


def test_every_section_explains_what_it_holds() -> None:
    caches = (cache(kind=CacheKind.UV, size=3 * MB), cache(kind=CacheKind.TRASH, size=9 * MB))
    sections = build_disk_sections(report=report(caches=caches), min_age_days=MIN_AGE)

    for section in sections:
        assert section.description == SECTION_DESCRIPTIONS[section.key]
        assert section.description
    assert "si ricrea" in SECTION_DESCRIPTIONS["caches"]


def test_disk_headline_sums_what_the_rows_can_free() -> None:
    docker = docker_disk(images=(image(char="d", tags=("reg:1",), size=5 * MB),))
    caches = (cache(kind=CacheKind.UV, size=3 * MB),)
    sections = build_disk_sections(
        report=report(docker=docker, caches=caches), min_age_days=MIN_AGE
    )

    assert disk_headline(sections=sections) == "Puoi liberare fino a 8 MB"


def test_disk_headline_counts_only_the_freeable_build_cache_and_no_user_data() -> None:
    docker = docker_disk(
        build_cache_size=10 * MB,
        build_cache_reclaimable=4 * MB,
        volumes=(volume(name="db", size=50 * MB),),
    )
    trash = (cache(kind=CacheKind.TRASH, size=9 * MB),)
    sections = build_disk_sections(report=report(docker=docker, caches=trash), min_age_days=MIN_AGE)

    # The volume and the trash are "Pericolo": their bytes are data, not a promise.
    assert disk_headline(sections=sections) == "Puoi liberare fino a 4 MB"


def test_last_scan_on_another_day_names_the_date() -> None:
    now = datetime(2026, 10, 18, 15, 0, tzinfo=LOCAL)
    assert last_scan_text(report=report(), now=now) == "Ultimo controllo il 16/10 alle 14:00"


def test_disk_headline_with_nothing_to_free_and_before_a_scan() -> None:
    assert disk_headline(sections=()) == ""
    nothing = build_disk_sections(report=report(), min_age_days=MIN_AGE)
    assert disk_headline(sections=nothing) == "Niente da liberare sul disco"


def test_untagged_image_reads_as_image_without_name() -> None:
    docker = docker_disk(images=(image(char="b", tags=(), dangling=True),))
    (row,) = sections_by_key(
        sections=build_disk_sections(report=report(docker=docker), min_age_days=MIN_AGE)
    )["images"].rows

    assert row.title == "Immagine senza nome"
    assert "sha256:" not in row.title
    assert row.subtitle.endswith("id " + "b" * 12)


def test_image_rows_state_risk_and_in_use_has_no_badge() -> None:
    docker = docker_disk(
        images=(
            image(char="a", tags=("app:1",), in_use=True),
            image(char="b", tags=(), dangling=True),
            image(char="c", tags=("loc:1",), local_build=True),
            image(char="d", tags=("reg:1",), size=5 * MB),
        )
    )
    rows = sections_by_key(
        sections=build_disk_sections(report=report(docker=docker), min_age_days=MIN_AGE)
    )["images"].rows
    by_title = {row.title: row for row in rows}
    assert by_title["app:1"].risk_text is None
    assert "in uso" in by_title["app:1"].subtitle
    assert by_title["Immagine senza nome"].risk_text == "Sicuro: si ricrea quando serve"
    assert by_title["loc:1"].risk_text == "Attenzione: leggi prima cosa si perde"
    assert by_title["loc:1"].risk_style == "warning"
    assert by_title["reg:1"].risk_text == "Sicuro: si ricrea quando serve"
    assert by_title["reg:1"].size_text == "5 MB"


def test_volume_rows_unknown_size_and_missing_created_at() -> None:
    docker = docker_disk(
        volumes=(
            volume(name="ok", size=2 * MB),
            volume(name="nosize", size=None),
            volume(name="nodate", created_at=""),
            volume(name="used", ref_count=2),
            volume(name="unknown_use", ref_count=None),
        )
    )
    rows = sections_by_key(
        sections=build_disk_sections(report=report(docker=docker), min_age_days=MIN_AGE)
    )["volumes"].rows
    by_title = {row.title: row for row in rows}
    assert by_title["ok"].risk_text == "Pericolo: cancella dati"
    assert by_title["ok"].risk_style == "error"
    assert by_title["nosize"].size_text == "dimensione sconosciuta"
    assert by_title["nodate"].risk_text is None
    assert "data di creazione" in by_title["nodate"].subtitle
    assert by_title["used"].risk_text is None
    assert "in uso" in by_title["used"].subtitle
    assert by_title["unknown_use"].risk_text is None
    assert by_title["unknown_use"].subtitle == "non sappiamo se un contenitore lo usa"


def test_containers_and_build_cache_rows() -> None:
    docker = docker_disk(
        containers=(stopped(cid="a"),),
        build_cache_size=10 * MB,
        build_cache_reclaimable=4 * MB,
        containers_truncated=3,
    )
    by_key = sections_by_key(
        sections=build_disk_sections(report=report(docker=docker), min_age_days=MIN_AGE)
    )
    container = by_key["containers"]
    assert container.rows[0].title == "ctr-a"
    assert container.rows[0].subtitle == "fermo"
    assert container.rows[0].risk_text == "Attenzione: leggi prima cosa si perde"
    assert container.more_text == "e altre 3"
    build = by_key["build_cache"].rows[0]
    assert build.size_text == "10 MB"
    assert "4 MB" in build.subtitle
    assert build.risk_text == "Sicuro: si ricrea quando serve"


def test_build_cache_with_nothing_to_reclaim_has_no_badge() -> None:
    docker = docker_disk(build_cache_size=MB, build_cache_reclaimable=0)
    by_key = sections_by_key(
        sections=build_disk_sections(report=report(docker=docker), min_age_days=MIN_AGE)
    )
    assert by_key["build_cache"].rows[0].risk_text is None


def test_docker_unavailable_shows_only_the_docker_section_message() -> None:
    unavailable = DockerDisk(
        status=DockerStatus(available=False, error="permission denied"),
        images=(),
        volumes=(),
        stopped_containers=(),
        build_cache_size=0,
        build_cache_reclaimable=0,
    )
    sections = build_disk_sections(
        report=report(docker=unavailable, caches=(cache(kind=CacheKind.UV),)), min_age_days=MIN_AGE
    )
    by_key = sections_by_key(sections=sections)
    assert by_key["docker"].message == "Docker non disponibile: permission denied"
    assert by_key["docker"].rows == ()
    assert not {"images", "volumes", "containers", "build_cache"} & set(by_key)
    assert by_key["caches"].message is None
    assert all(
        section.message is None or "Docker" not in section.message
        for key, section in by_key.items()
        if key != "docker"
    )


def test_caches_and_trash_are_separate_sections() -> None:
    caches = (cache(kind=CacheKind.UV, size=3 * MB), cache(kind=CacheKind.TRASH, size=9 * MB))
    by_key = sections_by_key(
        sections=build_disk_sections(report=report(caches=caches), min_age_days=MIN_AGE)
    )
    assert [row.title for row in by_key["caches"].rows] == ["uv"]
    assert by_key["caches"].rows[0].risk_text == "Sicuro: si ricrea quando serve"
    assert by_key["trash"].rows[0].size_text == "9 MB"
    assert by_key["trash"].rows[0].risk_text == "Pericolo: cancella dati"


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
    assert section.rows[0].title == "/p/9999/node_modules"
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


def test_rows_carry_action_kind_and_target_id() -> None:
    docker = docker_disk(volumes=(volume(name="v1"),), images=(image(char="a"),))
    by_key = sections_by_key(
        sections=build_disk_sections(report=report(docker=docker), min_age_days=MIN_AGE)
    )
    assert by_key["volumes"].rows[0].target_id == "v1"
    assert by_key["volumes"].rows[0].action_kind is ActionKind.VOLUME_REMOVE
    assert by_key["images"].rows[0].target_id == "sha256:" + "a" * 64
