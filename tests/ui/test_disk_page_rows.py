from datetime import datetime

import pytest

from tests.core.disk_helpers import devdir, report
from tests.ui.conftest import WindowFactory, main_context_iterate
from tests.ui.fakes import FakeDiskSource, FakeSource
from wimm.core.disk_wire import disk_report_from_json
from wimm.model.disk import DiskReport, DockerDisk
from wimm.model.enums import ActionKind, Risk
from wimm.model.snapshot import DockerStatus, Snapshot
from wimm.ui.disk_model import DiskRowView
from wimm.ui.pages.disk_rows import build_disk_row

pytestmark = pytest.mark.ui
from tests.ui.disk_page_helpers import SAMPLE, buttons_in, labels, make_page, scan_button, show


@pytest.fixture
def sample() -> DiskReport:
    return disk_report_from_json(text=SAMPLE.read_text(encoding="utf-8"))


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
