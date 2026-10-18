from collections.abc import Callable
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
from wimm.core.cache_catalog import withheld_kinds
from wimm.model.disk import CacheKind, DockerDisk
from wimm.model.enums import ActionKind
from wimm.model.snapshot import DockerStatus
from wimm.ui.disk_model import DiskRowView, DiskSectionView, more_text
from wimm.ui.disk_texts import (
    SECTION_DESCRIPTIONS,
    TIER_TITLES,
    DiskTotals,
    disk_headline,
    disk_totals,
    review_text,
    safe_label,
)
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


def test_every_cache_type_has_a_title_and_the_badge_of_its_own_risk() -> None:
    caches = tuple(
        cache(kind=kind, size=MB, ino=100 + index)
        for index, kind in enumerate(kind for kind in CacheKind if kind is not CacheKind.TRASH)
    )
    by_key = sections_by_key(
        sections=build_disk_sections(report=report(caches=caches), min_age_days=MIN_AGE)
    )
    rows = {row.title: row for row in by_key["caches"].rows}

    assert len(rows) == len(caches)
    assert (rows["Maven"].risk_text or "").startswith("Attenzione")
    assert (rows["Gradle"].risk_text or "").startswith("Sicuro")
    assert rows["Cargo (pacchetti)"].action_kind is ActionKind.CACHE_CLEAN
    assert rows["Modelli ollama"].risk_text == "Pericolo: cancella dati"
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


def test_sections_are_grouped_by_what_freeing_them_costs() -> None:
    docker = docker_disk(
        images=(image(char="a", tags=(), dangling=True),),
        volumes=(volume(name="db"),),
        containers=(stopped(cid="b"),),
        build_cache_size=10 * MB,
        build_cache_reclaimable=4 * MB,
    )
    caches = (cache(kind=CacheKind.UV), cache(kind=CacheKind.TRASH, ino=12))
    disk = report(docker=docker, caches=caches, devdirs=(devdir(path="/p/node_modules"),))

    sections = build_disk_sections(report=disk, min_age_days=MIN_AGE)

    assert [(s.tier, s.key) for s in sections] == [
        ("safe", "caches"),
        ("safe", "build_cache"),
        ("review", "images"),
        ("review", "containers"),
        ("review", "devdirs"),
        ("data", "volumes"),
        ("data", "trash"),
    ]
    assert TIER_TITLES["data"] == "Attenzione: cancella dati"


def test_mass_actions_say_how_much_they_free() -> None:
    docker = docker_disk(
        images=(
            image(char="a", tags=(), dangling=True, size=2 * MB),
            image(char="b", tags=("old:1",), size=5 * MB),
            image(char="c", tags=("app:1",), in_use=True, size=9 * MB),
        ),
        containers=(stopped(cid="d", size=3000),),
    )
    by_key = sections_by_key(
        sections=build_disk_sections(report=report(docker=docker), min_age_days=MIN_AGE)
    )

    assert [a.label for a in by_key["images"].actions] == [
        "Elimina immagini senza nome (2 MB)",
        "Elimina immagini inutilizzate (7 MB)",
    ]
    assert [a.label for a in by_key["containers"].actions] == ["Elimina container fermi (3 kB)"]


def test_safe_label_sums_only_the_safe_rows() -> None:
    docker = docker_disk(
        images=(image(char="a", tags=(), dangling=True, size=2 * MB),),
        volumes=(volume(name="db", size=50 * MB),),
        build_cache_size=10 * MB,
        build_cache_reclaimable=4 * MB,
    )
    caches = (
        cache(kind=CacheKind.UV, size=3 * MB),
        cache(kind=CacheKind.TRASH, size=9 * MB, ino=12),
    )
    sections = build_disk_sections(
        report=report(docker=docker, caches=caches), min_age_days=MIN_AGE
    )

    assert safe_label(sections=sections) == "Libera 9 MB senza rischi"
    assert safe_label(sections=build_disk_sections(report=report(), min_age_days=MIN_AGE)) == ""


def test_safe_label_header_and_plan_promise_the_same_amount() -> None:
    from tests.core.planning_helpers import NOW, OWNER_UID, snapshot
    from wimm.core.disk_rules import safe_reclaimable_bytes
    from wimm.core.planning import PlanningContext, plan_action
    from wimm.model.actions import ActionRequest
    from wimm.model.enums import PlanId
    from wimm.ui.format import format_size

    docker = docker_disk(
        images=(
            image(char="a", tags=(), dangling=True, size=2 * MB),
            image(char="b", tags=("loc:1",), local_build=True, size=7 * MB),
        ),
        volumes=(volume(name="db", size=50 * MB),),
        containers=(stopped(cid="c"),),
        build_cache_size=10 * MB,
        build_cache_reclaimable=4 * MB,
    )
    caches = (
        cache(kind=CacheKind.UV, size=3 * MB),
        cache(kind=CacheKind.TRASH, size=9 * MB, ino=12),
    )
    disk = report(docker=docker, caches=caches, devdirs=(devdir(path="/p/node_modules"),))
    context = PlanningContext(
        owner_uid=OWNER_UID, now=lambda: NOW, new_plan_id=lambda: PlanId("p"), disk_report=disk
    )
    plan = plan_action(
        request=ActionRequest(kind=ActionKind.DISK_FREE_SAFE), snapshot=snapshot(), context=context
    )
    sections = build_disk_sections(report=disk, min_age_days=MIN_AGE)

    total = safe_reclaimable_bytes(report=disk)
    assert plan.estimated_reclaim_disk == total
    assert safe_label(sections=sections) == f"Libera {format_size(size=total)} senza rischi"
