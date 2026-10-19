from datetime import datetime

import pytest

from tests.core.disk_helpers import MB, cache, devdir, docker_disk, report, volume
from wimm.core.disk_wire import disk_report_from_json
from wimm.model.disk import CacheKind, DiskReport, DockerDisk
from wimm.model.snapshot import DockerStatus
from wimm.ui.disk_model import DiskRowView
from wimm.ui.disk_texts import TIER_TITLES
from wimm.ui.format import format_size
from wimm.ui.pages.disk_rows import build_disk_row

pytestmark = pytest.mark.ui
from tests.ui.disk_page_helpers import SAMPLE, labels, make_page, scan_button, show


@pytest.fixture
def sample() -> DiskReport:
    return disk_report_from_json(text=SAMPLE.read_text(encoding="utf-8"))


def test_page_starts_waiting_with_no_scan_header(display: None, now: datetime) -> None:
    page = make_page()
    assert page.header_text == "Nessun controllo ancora"
    assert page.headline_text is None
    assert page.row_count == 0
    assert not page.is_scanning


def test_report_fills_sections_and_header(display: None, now: datetime, sample: DiskReport) -> None:
    page = make_page()
    show(page, report_=sample, now=now)
    # The sample report was scanned at 10:12 (scanned_at in the fixture).
    assert page.header_text == "Ultimo controllo alle 10:12"
    # D1 headline, by hand from the fixture: safe are uv 3,0 GB + dangling image 0,12 (unique
    # size) + build cache 0,07 = 3,19 GB. node_modules 0,70 + local image 0,45 + stopped
    # container 2 kB = 1,15 GB cost a rebuild. The volume and the trash are data: not counted.
    assert page.headline_text == "Puoi liberare 3,2 GB senza perdere niente"
    assert page.totals is not None
    assert format_size(size=page.totals.safe) == "3,2 GB"
    assert format_size(size=page.totals.review) == "1,2 GB"
    # F4: the dangling image is safe and sits in the safe tier; the local one stays.
    assert list(page.sections) == [
        "caches",
        "build_cache",
        "images_safe",
        "images",
        "containers",
        "devdirs",
        "volumes",
        "trash",
    ]
    tiers = [t for t in labels(page) if t in TIER_TITLES.values()]
    assert tiers == list(TIER_TITLES.values())
    # Rows in the fixture: 1 cache, 1 build cache, 2 images, 1 container, 1 dev dir,
    # 2 volumes, 1 trash.
    assert page.row_count == 9
    assert page.sections["devdirs"].row_count == len(sample.devdirs)


def test_scan_button_calls_rescan_and_shows_spinner_until_report(
    display: None, now: datetime, sample: DiskReport
) -> None:
    calls: list[str] = []
    page = make_page(calls=calls)
    show(page, report_=sample, now=now)
    rows_before = page.row_count

    scan_button(page).emit("clicked")

    # The click only asks; the scan state follows the service's disk-scan-started.
    assert calls == ["rescan"]
    assert not page.is_scanning
    page.begin_scan()
    assert page.is_scanning
    assert not scan_button(page).get_sensitive()
    assert all(g.spinner.get_visible() and g.spinner.get_spinning() for g in page.sections.values())
    assert page.row_count == rows_before

    other = report(devdirs=(devdir(path="/p/new/node_modules"),))
    show(page, report_=other, now=now)

    assert not page.is_scanning
    assert scan_button(page).get_sensitive()
    assert page.sections["devdirs"].row_count == 1
    assert not page.sections["devdirs"].spinner.get_visible()


def test_failed_scan_keeps_last_report_and_shows_notice(
    display: None, now: datetime, sample: DiskReport
) -> None:
    page = make_page()
    show(page, report_=sample, now=now)
    rows = page.row_count
    page.begin_scan()

    page.show_scan_failed()

    assert not page.is_scanning
    assert page.row_count == rows
    assert page.notice_text == "Il controllo non è riuscito: l'elenco mostra l'ultimo risultato."
    page.begin_scan()
    assert page.notice_text is None


def test_failed_first_scan_says_to_retry(display: None) -> None:
    page = make_page()
    page.begin_scan()
    page.show_scan_failed()
    assert page.notice_text == "Il controllo non è riuscito. Riprova con Controlla ora."
    assert page.row_count == 0


def test_empty_devdirs_message_is_visible(display: None, now: datetime) -> None:
    page = make_page()
    show(page, report_=report(), now=now)
    assert any("più vecchia di 90 giorni" in text for text in labels(page))
    assert page.sections["devdirs"].row_count == 0


def test_docker_unavailable_only_in_docker_section(display: None, now: datetime) -> None:
    down = DockerDisk(
        status=DockerStatus(available=False, error="socket assente"),
        images=(),
        volumes=(),
        stopped_containers=(),
        build_cache_size=0,
        build_cache_reclaimable=0,
    )
    page = make_page()
    show(page, report_=report(docker=down, caches=(cache(kind=CacheKind.UV),)), now=now)
    assert list(page.sections)[:2] == ["caches", "docker"]
    assert sum("Docker non disponibile: socket assente" in t for t in labels(page)) == 1
    assert page.sections["caches"].row_count == 1


def test_ten_thousand_devdirs_render_200_rows_and_counter(display: None, now: datetime) -> None:
    dirs = tuple(devdir(path=f"/p/{i}/node_modules", size=MB + i) for i in range(10_000))
    page = make_page()
    show(page, report_=report(devdirs=dirs), now=now)
    assert page.sections["devdirs"].row_count == 200
    assert page.sections["devdirs"].more_label == "e altre 9.800"
    assert "e altre 9.800" in labels(page)


def test_names_with_markup_characters_show_as_typed(display: None, now: datetime) -> None:
    docker = docker_disk(volumes=(volume(name="a&b<c>"),))
    row = DiskRowView(title="a&b<c>", subtitle="x & y", size_text="1 MB")
    widget = build_disk_row(row=row)
    assert widget.get_title() == "a&b<c>"
    assert not widget.get_use_markup()
    page = make_page()
    show(page, report_=report(docker=docker), now=now)
    assert "a&b<c>" in labels(page)
