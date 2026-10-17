from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import ClassVar, Protocol

import gi
import pytest

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, GObject, Gtk

from wimm.core.planning import PlanningContext, plan_action
from wimm.model.actions import ActionRequest, Plan
from wimm.model.enums import ActionKind, ActivityState, Category, GroupId, PlanId, Risk
from wimm.model.errors import WimmError
from wimm.model.memory import MemoryUse
from wimm.model.snapshot import (
    ActionOffer,
    ActivityAssessment,
    Group,
    Snapshot,
)
from wimm.serialize import snapshot_from_json
from wimm.ui.pages.overview import OverviewPage
from wimm.ui.window import MainWindow, create_main_window
from wimm.ui.window_state import SnapshotSource

FIXTURE = Path(__file__).parents[1] / "fixtures" / "snapshot_whitebox.json"
WAIT_TIMEOUT_S = 5.0
POLL_INTERVAL_US = 5000
SETTLE_MAX_ITERATIONS = 1000
IDLE_SINCE = datetime.fromisoformat("2026-10-16T05:12:00+02:00")


class FakeSource(GObject.Object):
    """Stands in for AppService: a snapshot, a failure counter and the update signal."""

    __gsignals__: ClassVar = {"snapshot-updated": (GObject.SignalFlags.RUN_LAST, None, ())}

    def __init__(self, *, snapshot: Snapshot | None, failures: int = 0) -> None:
        super().__init__()
        self._snapshot = snapshot
        self.consecutive_failures = failures

    def snapshot(self) -> Snapshot | None:
        return self._snapshot

    def publish(self, snapshot: Snapshot) -> None:
        self._snapshot = snapshot
        self.emit("snapshot-updated")


class FakeActionService(GObject.Object):
    """Stands in for AppService with actions: real planner, recorded execute calls."""

    __gsignals__: ClassVar = {
        "snapshot-updated": (GObject.SignalFlags.RUN_LAST, None, ()),
        "action-finished": (
            GObject.SignalFlags.RUN_LAST,
            None,
            (GObject.TYPE_STRING, GObject.TYPE_PYOBJECT),
        ),
        "action-rejected": (
            GObject.SignalFlags.RUN_LAST,
            None,
            (GObject.TYPE_STRING, GObject.TYPE_PYOBJECT),
        ),
    }

    def __init__(self, *, snapshot: Snapshot, plan_error: WimmError | None = None) -> None:
        super().__init__()
        self._snapshot = snapshot
        self.consecutive_failures = 0
        self.plan_error = plan_error
        self.planned: list[ActionRequest] = []
        self.executed: list[tuple[PlanId, str | None]] = []

    def snapshot(self) -> Snapshot:
        return self._snapshot

    def plan(self, *, request: ActionRequest) -> Plan:
        self.planned.append(request)
        if self.plan_error is not None:
            raise self.plan_error
        return plan_action(
            request=request, snapshot=self._snapshot, context=PlanningContext(owner_uid=1000)
        )

    def execute(self, *, plan_id: PlanId, typed_confirmation: str | None) -> None:
        self.executed.append((plan_id, typed_confirmation))


class RefreshableSource(FakeSource):
    refreshes = 0

    def request_refresh(self) -> None:
        self.refreshes += 1


@pytest.fixture(scope="session")
def display() -> None:
    if not Gtk.init_check():
        pytest.skip("no graphical display (run under xvfb-run)")
    Adw.init()


@pytest.fixture
def snapshot() -> Snapshot:
    return snapshot_from_json(text=FIXTURE.read_text())


@pytest.fixture
def now(snapshot: Snapshot) -> datetime:
    return snapshot.taken_at


def make_group(
    name: str,
    *,
    state: ActivityState = ActivityState.IDLE,
    reclaimable: int = 100,
    risk: Risk | None = Risk.SAFE,
    category: Category = Category.DEV_SERVER,
) -> Group:
    primary = None if risk is None else ActionOffer(kind=ActionKind.GROUP_STOP, risk=risk)
    return Group(
        id=GroupId(f"id-{name}"),
        name=name,
        category=category,
        activity=ActivityAssessment(
            state=state, since=IDLE_SINCE, reason="nessuna connessione in ingresso"
        ),
        memory=MemoryUse(used=reclaimable * 2, reclaimable=reclaimable),
        ports=(),
        primary_action=primary,
        ignored=False,
        snoozed_until=None,
        explanation="spiegazione",
        compose_project=None,
        members=(),
    )


def with_groups(snapshot: Snapshot, *groups: Group) -> Snapshot:
    return replace(snapshot, groups=groups)


def main_context_iterate() -> None:
    """Run the main-loop work that is ready now, without waiting for timeouts."""
    context = GLib.MainContext.default()
    while context.iteration(False):
        pass


def wait_until(
    condition: Callable[[], bool], *, description: str, timeout_s: float = WAIT_TIMEOUT_S
) -> None:
    """Spin the main loop until ``condition`` holds; fail with ``description`` on timeout."""
    deadline = GLib.get_monotonic_time() + int(timeout_s * 1_000_000)
    while not condition():
        if GLib.get_monotonic_time() >= deadline:
            pytest.fail(f"timed out after {timeout_s}s waiting for {description}")
        main_context_iterate()
        GLib.usleep(POLL_INTERVAL_US)


def settle(*, window_or_page: MainWindow | OverviewPage) -> None:
    """Wait until the overview has built its rows and the main loop has no ready work left."""
    page = window_or_page if isinstance(window_or_page, OverviewPage) else window_or_page.overview
    wait_until(lambda: not page.is_syncing, description="rows built")
    for _ in range(SETTLE_MAX_ITERATIONS):
        if not GLib.MainContext.default().pending():
            return
        main_context_iterate()
    pytest.fail(f"main loop still busy after {SETTLE_MAX_ITERATIONS} iterations")


def focus_is_in(window: Gtk.Window, widget: Gtk.Widget) -> bool:
    """True when the window focus is ``widget`` or one of its descendants."""
    focus = window.get_focus()
    return focus is not None and (focus is widget or focus.is_ancestor(widget))


def present_and_settle(window: MainWindow) -> None:
    """Present ``window``, wait for it to be mapped, then let the overview settle."""
    window.present()
    wait_until(window.get_mapped, description="window mapped")
    settle(window_or_page=window)


def descendants(widget: Gtk.Widget) -> Iterator[Gtk.Widget]:
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from descendants(child)
        child = child.get_next_sibling()


def idle_filter(overview: Gtk.Widget) -> Gtk.ToggleButton:
    toggles = [w for w in descendants(overview) if isinstance(w, Gtk.ToggleButton)]
    return next(t for t in toggles if t.get_label() == "Inattivi")


class WindowFactory(Protocol):
    """Builds a window; rows are settled unless ``settled`` is False."""

    def __call__(self, source: "SnapshotSource", *, settled: bool = True) -> MainWindow: ...


@pytest.fixture(scope="session")
def _registered_application(display: None) -> Gio.Application:
    # A process can export one org.gtk.Application object only, so the instance is shared.
    app = Gio.Application(
        application_id="io.github.wimm.UiTest", flags=Gio.ApplicationFlags.NON_UNIQUE
    )
    app.register()
    return app


@pytest.fixture
def application(_registered_application: Gio.Application) -> Iterator[Gio.Application]:
    yield _registered_application
    for name in _registered_application.list_actions():
        _registered_application.remove_action(name)


@pytest.fixture
def window_factory(
    display: None, application: Gio.Application, tmp_path: Path, now: datetime
) -> Iterator[WindowFactory]:
    windows: list[MainWindow] = []

    def build(source: SnapshotSource, *, settled: bool = True) -> MainWindow:
        window = create_main_window(
            application=application, source=source, clock=lambda: now, state_dir=tmp_path / "state"
        )
        windows.append(window)
        if settled:
            settle(window_or_page=window)
        return window

    yield build
    for window in windows:
        window.destroy()
    main_context_iterate()
