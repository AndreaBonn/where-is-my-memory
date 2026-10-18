from datetime import datetime
from pathlib import Path

import pytest
from gi.repository import Gtk

from tests.core.disk_helpers import MB, cache, devdir, docker_disk, report, volume
from tests.ui.conftest import WindowFactory, descendants, main_context_iterate
from tests.ui.fakes import FakeDiskSource, FakeSource
from wimm.core.disk_wire import disk_report_from_json
from wimm.model.disk import CacheKind, DiskReport, DockerDisk
from wimm.model.enums import ActionKind, Risk
from wimm.model.snapshot import DockerStatus, Snapshot
from wimm.ui.disk_model import DiskRowView
from wimm.ui.disk_texts import TIER_TITLES
from wimm.ui.format import format_size
from wimm.ui.pages.disk import DiskPage
from wimm.ui.pages.disk_header import SAFE_BUTTON_NAME
from wimm.ui.pages.disk_rows import build_disk_row

pytestmark = pytest.mark.ui

SAMPLE = Path(__file__).parents[1] / "fixtures" / "disk_report_sample.json"
MIN_AGE = 90


@pytest.fixture
def sample() -> DiskReport:
    return disk_report_from_json(text=SAMPLE.read_text(encoding="utf-8"))


def make_page(*, calls: list[str] | None = None) -> DiskPage:
    sink = calls if calls is not None else []
    return DiskPage(on_rescan=lambda: sink.append("rescan"))


def labels(widget: Gtk.Widget) -> list[str]:
    """The text each label shows, after markup parsing (``get_label`` returns the source)."""
    return [w.get_text() for w in descendants(widget) if isinstance(w, Gtk.Label)]


def scan_button(page: DiskPage) -> Gtk.Button:
    buttons = (w for w in descendants(page) if isinstance(w, Gtk.Button))
    return next(b for b in buttons if b.get_label() == "Controlla ora")


def show(page: DiskPage, *, report_: DiskReport | None, now: datetime) -> None:
    page.show_report(report=report_, now=now, min_age_days=MIN_AGE)


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


def buttons_in(widget: Gtk.Widget) -> list[Gtk.Button]:
    return [w for w in descendants(widget) if isinstance(w, Gtk.Button)]


def test_row_with_callback_has_action_button_that_calls_it(display: None) -> None:
    row = DiskRowView(
        title="v2",
        subtitle="non usato",
        size_text="1 MB",
        risk=Risk.DANGER,
        risk_text="Pericolo",
        risk_style="error",
        action_kind=ActionKind.VOLUME_REMOVE,
        target_id="v2",
    )
    got: list[DiskRowView] = []
    widget = build_disk_row(row=row, on_action=got.append)
    (button,) = buttons_in(widget)
    assert button.get_label() == "Rimuovi volume"
    button.emit("clicked")
    assert got == [row]


def test_row_without_callback_or_without_action_has_no_button(display: None) -> None:
    with_action = DiskRowView(
        title="v2",
        subtitle="x",
        size_text="1 MB",
        risk=Risk.DANGER,
        action_kind=ActionKind.VOLUME_REMOVE,
    )
    in_use = DiskRowView(title="v3", subtitle="in uso", size_text="1 MB")
    assert buttons_in(build_disk_row(row=with_action)) == []
    assert buttons_in(build_disk_row(row=in_use, on_action=lambda _row: None)) == []


def test_window_disk_page_follows_the_service(
    window_factory: WindowFactory, snapshot: Snapshot, sample: DiskReport
) -> None:
    source = FakeDiskSource(snapshot=snapshot, report=sample)
    window = window_factory(source)
    assert window.disk.row_count > 0
    assert window.disk.header_text.startswith("Ultimo controllo")

    scan_button(window.disk).emit("clicked")
    main_context_iterate()
    assert source.rescans == 1
    assert window.disk.is_scanning

    source.publish_report(report(devdirs=(devdir(path="/p/z/node_modules"),)))
    main_context_iterate()
    assert not window.disk.is_scanning
    assert window.disk.sections["devdirs"].row_count == 1

    window.disk.begin_scan()
    source.fail_scan()
    assert not window.disk.is_scanning
    assert window.disk.notice_text == (
        "Il controllo non è riuscito: l'elenco mostra l'ultimo risultato."
    )
    assert window.disk.sections["devdirs"].row_count == 1


def test_window_without_disk_scan_keeps_the_page_waiting(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    window = window_factory(FakeSource(snapshot=snapshot))
    assert window.disk.row_count == 0
    assert window.disk.header_text == "Nessun controllo ancora"


@pytest.mark.parametrize("error", ["a <b & c", "socket <unix>"])
def test_docker_error_with_markup_characters_is_shown_verbatim(
    display: None, now: datetime, error: str
) -> None:
    down = DockerDisk(
        status=DockerStatus(available=False, error=error),
        images=(),
        volumes=(),
        stopped_containers=(),
        build_cache_size=0,
        build_cache_reclaimable=0,
    )
    page = make_page()
    show(page, report_=report(docker=down), now=now)
    assert sum(f"Docker non disponibile: {error}" in t for t in labels(page)) == 1


def test_a_rescan_that_does_not_start_leaves_no_spinner(
    window_factory: WindowFactory, snapshot: Snapshot, sample: DiskReport
) -> None:
    source = FakeDiskSource(snapshot=snapshot, report=sample, can_scan=False)
    window = window_factory(source)
    scan_button(window.disk).emit("clicked")
    main_context_iterate()
    assert source.rescans == 1
    assert not window.disk.is_scanning


def test_a_scan_started_by_the_service_shows_the_spinner(
    window_factory: WindowFactory, snapshot: Snapshot, sample: DiskReport
) -> None:
    source = FakeDiskSource(snapshot=snapshot, report=sample)
    window = window_factory(source)
    assert not window.disk.is_scanning
    source.start_scan()
    main_context_iterate()
    assert window.disk.is_scanning
    assert source.rescans == 0


def test_a_window_opened_during_a_scan_shows_the_spinner(
    window_factory: WindowFactory, snapshot: Snapshot, sample: DiskReport
) -> None:
    source = FakeDiskSource(snapshot=snapshot, report=sample)
    source.start_scan()
    window = window_factory(source)
    assert window.disk.is_scanning


def test_safe_button_frees_everything_safe_with_one_click(
    display: None, now: datetime, sample: DiskReport
) -> None:
    calls: list[ActionKind] = []
    page = DiskPage(on_rescan=lambda: None, on_section=calls.append)
    show(page, report_=sample, now=now)

    (button,) = [b for b in buttons_in(page) if (b.get_label() or "").endswith("senza rischi")]
    assert (button.get_label() or "").startswith("Libera ")
    assert button.get_visible()
    button.emit("clicked")

    assert calls == [ActionKind.DISK_FREE_SAFE]


def test_safe_button_is_hidden_with_nothing_safe(display: None, now: datetime) -> None:
    page = DiskPage(on_rescan=lambda: None, on_section=lambda _kind: None)
    show(page, report_=report(), now=now)

    (button,) = [b for b in buttons_in(page) if b.get_name() == SAFE_BUTTON_NAME]
    assert not button.get_visible()


def safe_button(page: DiskPage) -> Gtk.Button:
    (button,) = [b for b in buttons_in(page) if b.get_name() == SAFE_BUTTON_NAME]
    return button


def test_safe_button_is_off_while_an_action_runs(
    display: None, now: datetime, sample: DiskReport
) -> None:
    page = DiskPage(on_rescan=lambda: None, on_section=lambda _kind: None)
    show(page, report_=sample, now=now)
    assert safe_button(page).get_sensitive()

    page.set_busy(busy=True)
    assert not safe_button(page).get_sensitive()

    page.set_busy(busy=False)
    assert safe_button(page).get_sensitive()


def test_safe_button_is_absent_without_actions(
    display: None, now: datetime, sample: DiskReport
) -> None:
    page = make_page()  # a source without the action service
    show(page, report_=sample, now=now)

    assert not safe_button(page).get_visible()


def _overview_texts(window: Gtk.Window) -> list[str]:
    overview = window.overview  # type: ignore[attr-defined]
    return [w.get_label() for w in descendants(overview) if isinstance(w, Gtk.Label)]


def test_the_overview_counts_the_disk_only_once_it_is_checked(
    window_factory: WindowFactory, snapshot: Snapshot, sample: DiskReport
) -> None:
    source = FakeDiskSource(snapshot=snapshot, report=None)
    window = window_factory(source)
    main_context_iterate()
    assert any(
        t.startswith("Il disco non è ancora stato controllato") for t in _overview_texts(window)
    )

    source.publish_report(sample)
    main_context_iterate()

    buttons = {w.get_name(): w for w in descendants(window.overview) if isinstance(w, Gtk.Button)}
    # Same safe amount as the Disco page headline above: 3,2 GB.
    assert buttons["free-disk-safe"].get_label() == "Libera 3,2 GB di disco"
    assert "Altri 1,2 GB se accetti di riscaricare o ricostruire" in _overview_texts(window)
    buttons["show-disk-page"].emit("clicked")
    assert window.view_stack.get_visible_child_name() == "disk"
