"""Service stand-ins for the UI tests: snapshot sources and an action service."""

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GObject

from wimm.config import Config, ConfigParseResult, update_config
from wimm.core.planning import PlanningContext, plan_action
from wimm.core.planning_restart import StoppedContainer
from wimm.model.actions import ActionRequest, Plan
from wimm.model.disk import DiskReport
from wimm.model.enums import GroupId, PlanId
from wimm.model.errors import WimmError
from wimm.model.snapshot import (
    Snapshot,
)
from wimm.paths import UserPaths


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
        "reclaim-measured": (
            GObject.SignalFlags.RUN_LAST,
            None,
            (GObject.TYPE_STRING, GObject.TYPE_PYOBJECT),
        ),
    }

    def __init__(
        self,
        *,
        snapshot: Snapshot,
        plan_error: WimmError | None = None,
        config: Config | None = None,
    ) -> None:
        super().__init__()
        self._snapshot = snapshot
        self.config_value = config if config is not None else Config()
        self.config_updates: list[dict[str, object]] = []
        # Non-empty: update_config reports these errors and keeps the config (a scripted service).
        self.scripted_errors: dict[str, str] = {}
        self.save_error: OSError | WimmError | None = None
        self.consecutive_failures = 0
        self.plan_error = plan_error
        self.planned: list[ActionRequest] = []
        self.executed: list[tuple[PlanId, str | None]] = []
        self.last_plan: Plan | None = None
        self.disk_report: DiskReport | None = None
        self.stopped: dict[str, tuple[StoppedContainer, ...]] = {}
        self.snoozed: list[tuple[GroupId, float]] = []
        self.ignored: list[tuple[GroupId, bool]] = []
        self.snoozed_all: list[float] = []
        self.extra_ignored: set[GroupId] = set()
        self.notifications_muted_until: datetime | None = None

    def snapshot(self) -> Snapshot:
        return self._snapshot

    def publish(self, snapshot: Snapshot) -> None:
        self._snapshot = snapshot
        self.emit("snapshot-updated")

    def config(self) -> Config:
        return self.config_value

    def ignored_group_ids(self) -> frozenset[GroupId]:
        return frozenset({g.id for g in self._snapshot.groups if g.ignored} | self.extra_ignored)

    def update_config(
        self, *, changes: Mapping[str, object], paths: UserPaths, home: Path
    ) -> ConfigParseResult:
        self.config_updates.append(dict(changes))
        if self.save_error is not None:
            raise self.save_error
        if self.scripted_errors:
            return ConfigParseResult(config=self.config_value, field_errors=self.scripted_errors)
        result = update_config(config=self.config_value, changes=changes, home=home)
        self.config_value = result.config
        return result

    def snooze(self, *, group_id: GroupId, duration_s: float) -> None:
        self.snoozed.append((group_id, duration_s))

    def set_ignored(self, *, group_id: GroupId, ignored: bool) -> None:
        self.ignored.append((group_id, ignored))

    def snooze_all(self, *, duration_s: float) -> None:
        self.snoozed_all.append(duration_s)

    def plan(self, *, request: ActionRequest) -> Plan:
        self.planned.append(request)
        if self.plan_error is not None:
            raise self.plan_error
        self.last_plan = plan_action(
            request=request,
            snapshot=self._snapshot,
            context=PlanningContext(
                owner_uid=1000, disk_report=self.disk_report, stopped=self.stopped
            ),
        )
        return self.last_plan

    def execute(self, *, plan_id: PlanId, typed_confirmation: str | None) -> None:
        self.executed.append((plan_id, typed_confirmation))


class RefreshableSource(FakeSource):
    refreshes = 0

    def request_refresh(self) -> None:
        self.refreshes += 1


class FakeDiskSource(FakeSource):
    """A snapshot source with the disk scan API of AppService: a report, a rescan counter."""

    __gsignals__: ClassVar = {
        "disk-report-updated": (GObject.SignalFlags.RUN_LAST, None, ()),
        "disk-scan-failed": (GObject.SignalFlags.RUN_LAST, None, ()),
        "disk-scan-started": (GObject.SignalFlags.RUN_LAST, None, ()),
    }

    def __init__(
        self, *, snapshot: Snapshot | None, report: DiskReport | None = None, can_scan: bool = True
    ) -> None:
        super().__init__(snapshot=snapshot)
        self._report = report
        self._can_scan = can_scan
        self._scanning = False
        self.rescans = 0

    def disk_scanning(self) -> bool:
        return self._scanning

    def start_scan(self) -> None:
        """A scan the service starts on its own, like the periodic one."""
        self._scanning = True
        self.emit("disk-scan-started")

    def disk_report(self) -> DiskReport | None:
        return self._report

    def rescan_disk(self) -> None:
        self.rescans += 1
        if self._can_scan:
            self.start_scan()

    def publish_report(self, report: DiskReport) -> None:
        self._report = report
        self._scanning = False
        self.emit("disk-report-updated")

    def fail_scan(self) -> None:
        self._scanning = False
        self.emit("disk-scan-failed")


class FakeDiskActionService(FakeActionService):
    """An action service that also has the disk scan API, so the Disco page can act.

    ``disk_report`` is a method here (like AppService); ``set_report`` swaps the report the
    planner reads without emitting an update.
    """

    disk_report: Any

    __gsignals__: ClassVar = {
        "disk-report-updated": (GObject.SignalFlags.RUN_LAST, None, ()),
        "disk-scan-failed": (GObject.SignalFlags.RUN_LAST, None, ()),
        "disk-scan-started": (GObject.SignalFlags.RUN_LAST, None, ()),
    }

    def __init__(self, *, snapshot: Snapshot, report: DiskReport | None) -> None:
        self._report: DiskReport | None = None
        super().__init__(snapshot=snapshot)
        self._report = report
        self.disk_report = lambda: self._report

    def set_report(self, report: DiskReport | None) -> None:
        self._report = report

    def disk_scanning(self) -> bool:
        return False

    def rescan_disk(self) -> None:
        self.rescans += 1

    rescans = 0

    def plan(self, *, request: ActionRequest) -> Plan:
        self.planned.append(request)
        if self.plan_error is not None:
            raise self.plan_error
        self.last_plan = plan_action(
            request=request,
            snapshot=self._snapshot,
            context=PlanningContext(owner_uid=1000, disk_report=self._report, stopped=self.stopped),
        )
        return self.last_plan
