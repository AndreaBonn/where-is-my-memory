"""The Disco page texts (headline, sections, rows, Docker states) in English."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

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
from wimm.i18n import _
from wimm.model.disk import CacheKind
from wimm.model.enums import ActionKind
from wimm.model.snapshot import DockerStatus
from wimm.ui.disk_model import DiskSectionView, more_text
from wimm.ui.disk_texts import SECTION_DESCRIPTIONS, TIER_TITLES, disk_headline, safe_label
from wimm.ui.disk_view import build_disk_sections, last_scan_text
from wimm.ui.format import button_label

pytestmark = pytest.mark.usefixtures("english")
MIN_AGE = 90
LOCAL = timezone(timedelta(hours=2))


def by_key(*, sections: tuple[DiskSectionView, ...]) -> dict[str, DiskSectionView]:
    return {section.key: section for section in sections}


def test_headline_and_safe_label_in_english() -> None:
    docker = docker_disk(images=(image(char="d", tags=("reg:1",), size=5 * MB),))
    caches = (cache(kind=CacheKind.UV, size=3 * MB),)
    sections = build_disk_sections(
        report=report(docker=docker, caches=caches), min_age_days=MIN_AGE
    )
    assert disk_headline(sections=sections) == "You can free up to 8 MB"
    assert safe_label(sections=sections) == "Free 8 MB with no risk"


def test_nothing_to_free_in_english() -> None:
    sections = build_disk_sections(report=report(), min_age_days=MIN_AGE)
    assert disk_headline(sections=sections) == "Nothing to free on the disk"


def test_last_scan_text_in_english() -> None:
    today = datetime(2026, 10, 16, 15, 0, tzinfo=LOCAL)
    later = datetime(2026, 10, 18, 15, 0, tzinfo=LOCAL)
    assert last_scan_text(report=report(), now=today) == "Last check at 14:00"
    assert last_scan_text(report=report(), now=later) == "Last check on 10/16 at 14:00"
    assert last_scan_text(report=None, now=today) == "No check yet"


def test_more_text_uses_the_english_thousands_separator() -> None:
    assert more_text(count=12_345) == "and 12,345 more"
    assert more_text(count=0) is None


def test_section_titles_and_descriptions_are_english() -> None:
    caches = (cache(kind=CacheKind.THUMBNAILS), cache(kind=CacheKind.TRASH))
    sections = by_key(
        sections=build_disk_sections(report=report(caches=caches), min_age_days=MIN_AGE)
    )
    assert sections["caches"].title == "Cache"
    assert sections["caches"].rows[0].title == "Thumbnails"
    assert sections["trash"].title == "Trash"
    assert sections["trash"].rows[0].title == "Trash"
    assert (
        sections["caches"].description
        == "Temporary files of development tools: they recreate themselves."
    )
    assert _(TIER_TITLES["data"]) == "Caution: deletes data"
    assert _(SECTION_DESCRIPTIONS["trash"]).startswith("Files you have already deleted")


def test_empty_sections_say_so_in_english() -> None:
    sections = by_key(sections=build_disk_sections(report=report(), min_age_days=MIN_AGE))
    assert sections["caches"].message == "No cache found"
    assert sections["trash"].message == "Trash not detected"
    assert sections["devdirs"].message == (
        "No dependency folder older than 90 days in the configured roots"
    )
    one_day = by_key(sections=build_disk_sections(report=report(), min_age_days=1))
    assert one_day["devdirs"].message == (
        "No dependency folder older than 1 day in the configured roots"
    )


@pytest.mark.parametrize(
    ("age_days", "expected"),
    [(1, "project idle for 1 day"), (120, "project idle for 120 days")],
)
def test_devdir_rows_pick_the_plural_in_english(age_days: int, expected: str) -> None:
    dirs = (devdir(path="/p/a/node_modules", age_days=age_days),)
    sections = by_key(sections=build_disk_sections(report=report(devdirs=dirs), min_age_days=1))
    assert sections["devdirs"].title == "Dependency folders"
    assert sections["devdirs"].rows[0].subtitle == expected


def test_image_rows_describe_their_state_in_english() -> None:
    docker = docker_disk(
        images=(
            image(char="a", tags=(), dangling=True, local_build=True),
            image(char="b", tags=("app:1",), in_use=True),
        )
    )
    section = by_key(
        sections=build_disk_sections(report=report(docker=docker), min_age_days=MIN_AGE)
    )["images"]
    unnamed, used = section.rows
    assert section.title == "Docker images"
    assert unnamed.title == "Unnamed image"
    assert unnamed.subtitle == "not in use · unnamed · built locally · id " + "a" * 12
    assert used.subtitle == "used by a container"
    # A dangling image can be recreated, the one in use has no button at all.
    assert unnamed.risk_text == "Safe: it recreates itself when needed"
    assert used.risk_text is None


def test_volume_and_container_rows_and_buttons_are_english() -> None:
    docker = docker_disk(
        volumes=(
            volume(name="ok"),
            volume(name="used", ref_count=2),
            volume(name="unknown", ref_count=None),
            volume(name="nodate", created_at=""),
            volume(name="nosize", size=None),
        ),
        containers=(stopped(cid="a"),),
        build_cache_size=10 * MB,
    )
    sections = by_key(
        sections=build_disk_sections(report=report(docker=docker), min_age_days=MIN_AGE)
    )
    states = {row.title: row.subtitle for row in sections["volumes"].rows}
    assert sections["volumes"].title == "Docker volumes"
    assert states["ok"] == "unused"
    assert states["used"] == "used by a container"
    assert states["unknown"] == "we don't know if a container uses it"
    assert states["nodate"] == "cannot be removed: creation date unknown"
    assert sections["volumes"].rows[-1].size_text == "unknown size"
    assert sections["containers"].rows[0].subtitle == "stopped"
    assert sections["containers"].title == "Stopped containers"
    assert (
        sections["containers"]
        .actions[0]
        .label.startswith(button_label(kind=ActionKind.CONTAINERS_PRUNE_STOPPED))
    )
    assert sections["containers"].actions[0].label.startswith("Delete stopped containers (")
    build = sections["build_cache"]
    assert build.title == "Docker build cache"
    assert (build.rows[0].title, build.rows[0].subtitle) == ("Build cache", "10 MB can be freed")


def test_docker_unavailable_names_the_cause_in_english() -> None:
    base = report()
    status = DockerStatus(available=False, error="no socket")
    broken = replace(base, docker=replace(base.docker, status=status))

    section = by_key(sections=build_disk_sections(report=broken, min_age_days=MIN_AGE))["docker"]

    assert section.title == "Docker"
    assert section.message == "Docker not available: no socket"
