from datetime import datetime, timedelta, timezone

from tests.core.disk_helpers import (
    MB,
    cache,
    docker_disk,
    image,
    report,
    volume,
)
from tests.ui.disk_view_helpers import MIN_AGE, sections_by_key
from wimm.model.disk import CacheKind
from wimm.ui.disk_texts import (
    SECTION_DESCRIPTIONS,
    DiskTotals,
    disk_headline,
    disk_totals,
    review_text,
)
from wimm.ui.disk_view import build_disk_sections, last_scan_text

LOCAL = timezone(timedelta(hours=2))


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
    by_key = sections_by_key(sections=sections)
    # Hand-written oracle: the dict above cannot vouch for itself.
    assert by_key["caches"].description == (
        "File temporanei dei programmi di sviluppo: si ricreano da soli."
    )
    assert by_key["trash"].description == (
        "File che hai già cancellato: svuotandolo spariscono per sempre."
    )


def test_disk_headline_sums_what_the_rows_can_free() -> None:
    docker = docker_disk(images=(image(char="d", tags=("reg:1",), size=5 * MB),))
    caches = (cache(kind=CacheKind.UV, size=3 * MB),)
    sections = build_disk_sections(
        report=report(docker=docker, caches=caches), min_age_days=MIN_AGE
    )

    assert disk_headline(sections=sections) == "Puoi liberare 8 MB senza perdere niente"


def test_disk_headline_counts_only_the_freeable_build_cache_and_no_user_data() -> None:
    docker = docker_disk(
        build_cache_size=10 * MB,
        build_cache_reclaimable=4 * MB,
        volumes=(volume(name="db", size=50 * MB),),
    )
    trash = (cache(kind=CacheKind.TRASH, size=9 * MB),)
    sections = build_disk_sections(report=report(docker=docker, caches=trash), min_age_days=MIN_AGE)

    # The volume and the trash are "Pericolo": their bytes are data, not a promise.
    assert disk_headline(sections=sections) == "Puoi liberare 4 MB senza perdere niente"


def test_disk_totals_split_the_safe_bytes_from_those_that_cost_a_rebuild() -> None:
    docker = docker_disk(
        images=(
            image(char="d", tags=("reg:1",), size=5 * MB),
            image(char="e", size=2 * MB, local_build=True),
        ),
        volumes=(volume(name="db", size=50 * MB),),
    )
    caches = (cache(kind=CacheKind.UV, size=3 * MB), cache(kind=CacheKind.TRASH, size=9 * MB))
    sections = build_disk_sections(
        report=report(docker=docker, caches=caches), min_age_days=MIN_AGE
    )

    # Safe: pulled image 5 + uv 3. To rebuild: the local image 2. Volume and trash are data.
    assert disk_totals(sections=sections) == DiskTotals(safe=8 * MB, review=2 * MB)
    assert review_text(totals=disk_totals(sections=sections)) == (
        "Altri 2 MB se accetti di riscaricare o ricostruire"
    )


def test_disk_totals_before_a_scan_are_none() -> None:
    assert disk_totals(sections=()) is None
    assert review_text(totals=None) == ""


def test_with_nothing_safe_the_headline_says_so_and_the_rest_is_offered_apart() -> None:
    docker = docker_disk(images=(image(char="e", size=2 * MB, local_build=True),))
    sections = build_disk_sections(report=report(docker=docker), min_age_days=MIN_AGE)

    assert disk_headline(sections=sections) == "Niente da liberare senza perdere qualcosa"
    assert review_text(totals=disk_totals(sections=sections)) == (
        "2 MB si liberano se accetti di riscaricare o ricostruire"
    )
    assert review_text(totals=DiskTotals(safe=MB, review=0)) == ""


def test_last_scan_on_another_day_names_the_date() -> None:
    now = datetime(2026, 10, 18, 15, 0, tzinfo=LOCAL)
    assert last_scan_text(report=report(), now=now) == "Ultimo controllo il 16/10 alle 14:00"


def test_disk_headline_with_nothing_to_free_and_before_a_scan() -> None:
    assert disk_headline(sections=()) == ""
    nothing = build_disk_sections(report=report(), min_age_days=MIN_AGE)
    assert disk_headline(sections=nothing) == "Niente da liberare sul disco"
