"""R2: a saved project folder that is gone is flagged, and no folder at all is an empty state."""

from datetime import datetime
from pathlib import Path

import pytest
from gi.repository import Adw, Gtk

from tests.core.disk_helpers import report
from tests.ui.conftest import descendants
from tests.ui.fakes import FakeDiskSource
from wimm.config import Config
from wimm.core.root_policy import RootRefusal
from wimm.model.disk import DiskReport
from wimm.model.snapshot import Snapshot
from wimm.ui.disk_model import RootsState
from wimm.ui.disk_view import build_disk_sections
from wimm.ui.pages.disk import DiskPage
from wimm.ui.window_disk import DiskBinding

pytestmark = pytest.mark.ui

MIN_AGE = 90
GONE = "/home/me/old-projects"
CHOOSE = "Scegli una cartella"
EMPTY_TITLE = "Nessuna cartella di progetti trovata"
NO_DEVDIRS = "Nessuna cartella di dipendenze più vecchia"


def make_page(*, chosen: list[str] | None = None) -> DiskPage:
    sink = chosen if chosen is not None else []
    return DiskPage(on_rescan=lambda: None, on_choose_folder=lambda: sink.append("choose"))


def show(page: DiskPage, *, roots: RootsState, now: datetime) -> None:
    page.show_report(report=report(), now=now, min_age_days=MIN_AGE, roots=roots)


def row_titles(page: DiskPage) -> list[str]:
    return [w.get_title() for w in descendants(page) if isinstance(w, Adw.ActionRow)]


def page_texts(page: DiskPage) -> list[str]:
    return [w.get_text() for w in descendants(page) if isinstance(w, Gtk.Label)]


def button(page: DiskPage, label: str) -> Gtk.Button | None:
    buttons = (w for w in descendants(page) if isinstance(w, Gtk.Button))
    return next((b for b in buttons if b.get_label() == label), None)


def test_view_lists_a_warning_per_missing_root() -> None:
    roots = RootsState(missing=(GONE, "/mnt/x"))
    sections = build_disk_sections(report=report(), min_age_days=MIN_AGE, roots=roots)
    devdirs = next(s for s in sections if s.key == "devdirs")
    assert devdirs.warnings == (f"La cartella {GONE} non esiste", "La cartella /mnt/x non esiste")


def test_view_has_no_warning_when_every_root_exists() -> None:
    sections = build_disk_sections(report=report(), min_age_days=MIN_AGE, roots=RootsState())
    assert next(s for s in sections if s.key == "devdirs").warnings == ()


def test_missing_root_is_announced_as_text_in_the_devdirs_section(
    display: None, now: datetime
) -> None:
    page = make_page()
    show(page, roots=RootsState(missing=(GONE,), usable=True), now=now)
    assert f"La cartella {GONE} non esiste" in row_titles(page)
    # The valid roots still count: no empty state.
    assert button(page, CHOOSE) is None


def test_no_warning_when_nothing_is_missing(display: None, now: datetime) -> None:
    page = make_page()
    show(page, roots=RootsState(), now=now)
    assert not [t for t in row_titles(page) if t.startswith("La cartella")]
    # Positive pair: the dev dirs section is rendered, with its "nothing old" line.
    assert [t for t in page_texts(page) if NO_DEVDIRS in t]
    assert button(page, CHOOSE) is None


def test_no_usable_root_shows_the_empty_state_with_its_action(display: None, now: datetime) -> None:
    chosen: list[str] = []
    page = make_page(chosen=chosen)
    show(page, roots=RootsState(missing=(), usable=False), now=now)
    assert EMPTY_TITLE in row_titles(page)
    action = button(page, CHOOSE)
    assert action is not None
    action.emit("clicked")
    assert chosen == ["choose"]
    assert not [t for t in page_texts(page) if NO_DEVDIRS in t]


def test_all_roots_missing_shows_both_warnings_and_empty_state(
    display: None, now: datetime
) -> None:
    page = make_page()
    show(page, roots=RootsState(missing=(GONE,), usable=False), now=now)
    titles = row_titles(page)
    assert EMPTY_TITLE in titles
    assert f"La cartella {GONE} non esiste" in titles


def test_empty_state_has_no_button_without_a_way_to_open_preferences(
    display: None, now: datetime
) -> None:
    page = DiskPage(on_rescan=lambda: None)
    show(page, roots=RootsState(usable=False), now=now)
    assert EMPTY_TITLE in row_titles(page)
    assert button(page, CHOOSE) is None


class ConfigSource(FakeDiskSource):
    def __init__(self, *, snapshot: Snapshot, config: Config, report_: DiskReport) -> None:
        super().__init__(snapshot=snapshot, report=report_)
        self.config_value = config

    def config(self) -> Config:
        return self.config_value


def test_binding_reads_the_missing_roots_from_the_config(
    display: None,
    now: datetime,
    snapshot: Snapshot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # tmp_path sits under /tmp, which the real policy refuses; this test is about "missing".
    monkeypatch.setattr(Config, "refused_roots", property(lambda _self: ()))
    gone = tmp_path / "gone"
    config = Config(devdirs_roots=(tmp_path, gone))
    source = ConfigSource(snapshot=snapshot, config=config, report_=report())
    binding = DiskBinding(source=source, clock=lambda: now)
    assert f"La cartella {gone} non esiste" in row_titles(binding.page)
    assert button(binding.page, CHOOSE) is None


def test_binding_shows_the_empty_state_when_no_root_exists(
    display: None, now: datetime, snapshot: Snapshot, tmp_path: Path
) -> None:
    config = Config(devdirs_roots=())
    source = ConfigSource(snapshot=snapshot, config=config, report_=report())
    calls: list[str] = []
    binding = DiskBinding(
        source=source, clock=lambda: now, on_choose_folder=lambda: calls.append("x")
    )
    action = button(binding.page, CHOOSE)
    assert action is not None
    action.emit("clicked")
    assert calls == ["x"]


def test_binding_refreshes_the_notice_when_the_roots_change(
    display: None, now: datetime, snapshot: Snapshot, tmp_path: Path
) -> None:
    gone = tmp_path / "gone"
    source = ConfigSource(snapshot=snapshot, config=Config(devdirs_roots=(gone,)), report_=report())
    binding = DiskBinding(source=source, clock=lambda: now)
    assert f"La cartella {gone} non esiste" in row_titles(binding.page)
    source.config_value = Config(devdirs_roots=(tmp_path,))
    source.emit("snapshot-updated")
    assert not [t for t in row_titles(binding.page) if t.startswith("La cartella")]


def test_binding_does_not_probe_the_disk_on_every_snapshot(
    display: None,
    now: datetime,
    snapshot: Snapshot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probes: list[int] = []
    real: property = Config.__dict__["missing_roots"]

    def counted(self: Config) -> tuple[Path, ...]:
        probes.append(1)
        found: tuple[Path, ...] = real.__get__(self)
        return found

    monkeypatch.setattr(Config, "missing_roots", property(counted))
    source = ConfigSource(
        snapshot=snapshot, config=Config(devdirs_roots=(tmp_path,)), report_=report()
    )
    DiskBinding(source=source, clock=lambda: now)
    before = len(probes)
    for _ in range(5):
        source.emit("snapshot-updated")
    # A root on a stuck network mount would freeze the window at every tick.
    assert len(probes) == before
    source.config_value = Config(devdirs_roots=(tmp_path / "gone",))
    source.emit("snapshot-updated")
    assert len(probes) == before + 1


def test_binding_shows_the_empty_state_when_every_root_is_refused(
    display: None,
    now: datetime,
    snapshot: Snapshot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refused = ((tmp_path, RootRefusal.SYSTEM_PATH),)
    monkeypatch.setattr(Config, "refused_roots", property(lambda _self: refused))
    source = ConfigSource(
        snapshot=snapshot, config=Config(devdirs_roots=(tmp_path,)), report_=report()
    )
    binding = DiskBinding(source=source, clock=lambda: now, on_choose_folder=lambda: None)
    assert EMPTY_TITLE in row_titles(binding.page)
    assert button(binding.page, CHOOSE) is not None


def test_binding_keeps_the_page_usable_when_only_some_roots_are_refused(
    display: None,
    now: datetime,
    snapshot: Snapshot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refused = ((tmp_path / "sys", RootRefusal.SYSTEM_PATH),)
    monkeypatch.setattr(Config, "refused_roots", property(lambda _self: refused))
    config = Config(devdirs_roots=(tmp_path, tmp_path / "sys"))
    source = ConfigSource(snapshot=snapshot, config=config, report_=report())
    binding = DiskBinding(source=source, clock=lambda: now, on_choose_folder=lambda: None)
    assert EMPTY_TITLE not in row_titles(binding.page)
    # The valid root keeps the page working: its dev dirs section is rendered.
    assert [t for t in page_texts(binding.page) if NO_DEVDIRS in t]
    assert button(binding.page, CHOOSE) is None
