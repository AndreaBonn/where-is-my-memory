from dataclasses import replace
from pathlib import Path

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
from tests.ui.disk_view_helpers import MIN_AGE, sections_by_key
from wimm.model.disk import CacheKind, DockerDisk
from wimm.model.enums import ActionKind, Risk
from wimm.ui.disk_texts import (
    TIER_TITLES,
    safe_label,
)
from wimm.ui.disk_view import build_disk_sections


def test_rows_carry_action_kind_and_target_id() -> None:
    docker = docker_disk(volumes=(volume(name="v1"),), images=(image(char="a"),))
    by_key = sections_by_key(
        sections=build_disk_sections(report=report(docker=docker), min_age_days=MIN_AGE)
    )
    assert by_key["volumes"].rows[0].target_id == "v1"
    assert by_key["volumes"].rows[0].action_kind is ActionKind.VOLUME_REMOVE
    assert by_key["images_safe"].rows[0].target_id == "sha256:" + "a" * 64


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
        ("safe", "images_safe"),
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

    # All unused images are pulled ones: both buttons sit with them in the safe tier.
    assert [a.label for a in by_key["images_safe"].actions] == [
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


def test_an_image_pinned_by_digest_reads_as_its_repository() -> None:
    # F7: "ghcr.io/berriai/litellm@sha256:b6d3e2…" filled the whole row.
    digest = "sha256:" + "b6d3e2b93af9" + "0" * 52
    docker = docker_disk(images=(image(char="a", tags=(f"ghcr.io/berriai/litellm@{digest}",)),))
    (row,) = sections_by_key(
        sections=build_disk_sections(report=report(docker=docker), min_age_days=MIN_AGE)
    )["images_safe"].rows

    assert row.title == "ghcr.io/berriai/litellm"
    assert "versione fissata b6d3e2b93af9" in row.subtitle


def test_a_dependency_folder_reads_as_project_and_folder() -> None:
    # F7: the absolute path was the title; a generic folder name takes its parent along.
    home = str(Path.home())
    folders = (
        devdir(path=f"{home}/P/my-hub/node_modules"),
        devdir(path=f"{home}/P/generali/demo-generali/frontend/node_modules"),
    )
    rows = sections_by_key(
        sections=build_disk_sections(report=report(devdirs=folders), min_age_days=MIN_AGE)
    )["devdirs"].rows

    assert [row.title for row in rows] == [
        "my-hub · node_modules",
        "demo-generali/frontend · node_modules",
    ]
    assert rows[0].subtitle.startswith("~/P/my-hub/node_modules · progetto fermo da")


def test_every_row_sits_in_the_tier_of_its_own_risk() -> None:
    # F4: "Si libera senza pensarci" held Maven ("Attenzione") and "Da guardare prima" held
    # pulled images ("Sicuro").
    docker = docker_disk(
        images=(
            image(char="a", tags=("alpine:3",)),
            image(char="b", tags=("myapp:dev",), local_build=True),
        )
    )
    caches = (
        cache(kind=CacheKind.UV, size=3 * MB, ino=1),
        cache(kind=CacheKind.MAVEN, size=2 * MB, ino=2),
        cache(kind=CacheKind.OLLAMA, size=MB, ino=3),
    )
    sections = build_disk_sections(
        report=report(docker=docker, caches=caches), min_age_days=MIN_AGE
    )

    expected = {"safe": {Risk.SAFE}, "review": {Risk.CAUTION}, "data": {Risk.DANGER}}
    for section in sections:
        for row in section.rows:
            if row.action_kind is not None and section.tier in expected:
                assert row.risk in expected[section.tier], (section.key, row.title)
    by_key = sections_by_key(sections=sections)
    assert [r.title for r in by_key["caches"].rows] == ["uv"]
    assert [r.title for r in by_key["caches_review"].rows] == ["Maven"]
    assert [r.title for r in by_key["caches_data"].rows] == ["Modelli ollama"]
    assert [r.title for r in by_key["images_safe"].rows] == ["alpine:3"]
    assert [r.title for r in by_key["images"].rows] == ["myapp:dev"]


def test_mass_actions_follow_the_rows_they_act_on() -> None:
    only_safe = docker_disk(images=(image(char="a", tags=(), dangling=True),))
    mixed = docker_disk(
        images=(
            image(char="a", tags=(), dangling=True),
            image(char="b", tags=("loc:1",), local_build=True),
        )
    )

    def placed(docker: DockerDisk) -> dict[str, list[ActionKind]]:
        sections = build_disk_sections(report=report(docker=docker), min_age_days=MIN_AGE)
        return {s.key: [a.kind for a in s.actions] for s in sections if "images" in s.key}

    # Only safe rows: no empty "Da guardare prima" section left holding the button.
    assert placed(only_safe) == {"images_safe": [ActionKind.IMAGES_PRUNE_DANGLING]}
    assert placed(mixed) == {
        "images_safe": [ActionKind.IMAGES_PRUNE_DANGLING],
        "images": [ActionKind.IMAGES_PRUNE_UNUSED],
    }


def test_hidden_images_stay_counted_when_every_shown_image_is_safe() -> None:
    docker = replace(docker_disk(images=(image(char="a", tags=("alpine:3",)),)), images_truncated=7)
    by_key = sections_by_key(
        sections=build_disk_sections(report=report(docker=docker), min_age_days=MIN_AGE)
    )

    assert "images" not in by_key
    assert by_key["images_safe"].more_text == "e altre 7"
