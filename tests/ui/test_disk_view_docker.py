from tests.core.disk_helpers import (
    MB,
    cache,
    docker_disk,
    image,
    report,
    stopped,
    volume,
)
from tests.ui.disk_view_helpers import MIN_AGE, sections_by_key
from wimm.model.disk import CacheKind, DockerDisk
from wimm.model.snapshot import DockerStatus
from wimm.ui.disk_view import build_disk_sections


def test_untagged_image_reads_as_image_without_name() -> None:
    docker = docker_disk(images=(image(char="b", tags=(), dangling=True),))
    (row,) = sections_by_key(
        sections=build_disk_sections(report=report(docker=docker), min_age_days=MIN_AGE)
    )["images_safe"].rows

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
    by_key = sections_by_key(
        sections=build_disk_sections(report=report(docker=docker), min_age_days=MIN_AGE)
    )
    rows = by_key["images"].rows + by_key["images_safe"].rows
    by_title = {row.title: row for row in rows}
    assert by_title["app:1"].risk_text is None
    assert "in uso" in by_title["app:1"].subtitle
    assert by_title["Immagine senza nome"].risk_text == "Sicuro"
    assert by_title["loc:1"].risk_text == "Attenzione"
    assert by_title["loc:1"].risk_style == "warning"
    assert by_title["reg:1"].risk_text == "Sicuro"
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
    assert by_title["ok"].risk_text == "Pericolo"
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
    assert container.rows[0].risk_text == "Attenzione"
    assert container.more_text == "e altre 3"
    build = by_key["build_cache"].rows[0]
    assert build.size_text == "10 MB"
    assert "4 MB" in build.subtitle
    assert build.risk_text == "Sicuro"


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
