"""Disk page rebuilds: sections that change keys, busy state, missing handlers."""

from dataclasses import replace
from datetime import datetime

import pytest
from gi.repository import Adw, Gtk

from tests.core.disk_helpers import report
from tests.ui.conftest import (
    descendants,
)
from tests.ui.disk_page_helpers import SAMPLE, make_page, scan_button, show
from tests.ui.test_ui_widget_gaps import buttons_of
from wimm.core.disk_wire import disk_report_from_json
from wimm.model.disk import DiskReport, DockerDisk
from wimm.model.snapshot import DockerStatus
from wimm.ui.disk_texts import TIER_TITLES
from wimm.ui.pages.disk import DiskPage

pytestmark = pytest.mark.ui


def sample_report() -> DiskReport:
    return disk_report_from_json(text=SAMPLE.read_text(encoding="utf-8"))


def docker_down() -> DockerDisk:
    return DockerDisk(
        status=DockerStatus(available=False, error="socket"),
        images=(),
        volumes=(),
        stopped_containers=(),
        build_cache_size=0,
        build_cache_reclaimable=0,
    )


def tier_labels(page: Gtk.Widget) -> list[str]:
    titles = set(TIER_TITLES.values())
    return [
        w.get_text()
        for w in descendants(page)
        if isinstance(w, Gtk.Label) and w.get_text() in titles
    ]


def test_rebuild_after_the_sections_change_leaves_no_duplicate_titles_or_orphans(
    display: None, now: datetime
) -> None:
    page = make_page()
    show(page, report_=disk_report_from_json(text=SAMPLE.read_text(encoding="utf-8")), now=now)
    assert len(tier_labels(page)) == len(TIER_TITLES)
    first_keys = list(page.sections)

    show(page, report_=report(docker=docker_down()), now=now)

    assert list(page.sections) != first_keys
    groups = [w for w in descendants(page) if isinstance(w, Adw.PreferencesGroup)]
    assert len(groups) == len(page.sections)
    labels = tier_labels(page)
    assert len(labels) == len(set(labels))


def test_busy_survives_a_rebuild_of_the_sections(display: None, now: datetime) -> None:
    page = DiskPage(
        on_rescan=lambda: None, on_action=lambda _row: None, on_section=lambda _kind: None
    )
    show(page, report_=disk_report_from_json(text=SAMPLE.read_text(encoding="utf-8")), now=now)
    page.set_busy(busy=True)

    show(page, report_=replace(sample_report(), docker=docker_down()), now=now)

    section_buttons = [b for g in page.sections.values() for b in buttons_of(g.group)]
    assert section_buttons
    assert not any(b.get_sensitive() for b in section_buttons)
    page.set_busy(busy=False)
    assert all(b.get_sensitive() for b in section_buttons)


def test_section_buttons_do_nothing_without_a_section_handler(display: None, now: datetime) -> None:
    page = make_page()
    show(page, report_=disk_report_from_json(text=SAMPLE.read_text(encoding="utf-8")), now=now)
    section_buttons = [b for g in page.sections.values() for b in buttons_of(g.group)]
    assert section_buttons

    for button in section_buttons:
        button.emit("clicked")

    assert scan_button(page).get_sensitive()
    assert not page.is_scanning


# --- widgets ----------------------------------------------------------------------------
