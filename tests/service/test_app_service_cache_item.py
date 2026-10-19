from dataclasses import dataclass

from tests.core.disk_helpers import MB, report
from tests.service.app_service_actions_helpers import FakeExecutor
from tests.service.app_service_disk_helpers import Rig, build_rig, disk_action_service
from tests.service.service_helpers import spin_for, spin_until
from wimm.model import CacheEntry, CacheItem, CacheItemKind, CacheKind
from wimm.model.actions import ActionRequest, Plan, selected_entry_id
from wimm.model.enums import ActionKind, TargetId
from wimm.service.control_protocols import StepOutcome, StepStatus
from wimm.service.errors import TargetChanged

HUB = "/home/u/.cache/huggingface"
ITEM_ID = "models--org--a"
FREED = 7 * MB
REQUEST = ActionRequest(
    kind=ActionKind.CACHE_ITEM_REMOVE, target_id=TargetId(f"huggingface:{ITEM_ID}")
)


@dataclass
class FreeingExecutor(FakeExecutor):
    """Reports the bytes the removal freed, like the real disk-fs executor."""

    def execute(self, *, plan: Plan) -> tuple[StepOutcome, ...]:
        super().execute(plan=plan)
        return tuple(
            StepOutcome(order=s.order, status=StepStatus.DONE, freed_bytes=FREED)
            for s in plan.steps
        )


def _rig_with_item() -> Rig:
    item = CacheItem(
        id=ITEM_ID,
        title="org/a",
        path=f"{HUB}/hub/{ITEM_ID}",
        size=3 * MB,
        st_ino=5,
        st_dev=2049,
        kind=CacheItemKind.HF_MODEL,
    )
    entry = CacheEntry(
        kind=CacheKind.HUGGINGFACE, path=HUB, size=5 * MB, st_ino=11, st_dev=2049, items=(item,)
    )
    rig = build_rig()
    rig.scanner.result = report(caches=(entry,))
    rig.scanner.gate.set()
    return rig


def test_a_cache_item_removal_reports_freed_bytes_and_rescans_the_disk() -> None:
    rig = _rig_with_item()
    executor = FreeingExecutor()
    service = disk_action_service(rig, executor)
    outcomes: list[tuple[StepOutcome, ...]] = []
    service.connect("action-finished", lambda _s, _p, o: outcomes.append(o))
    try:
        scans = len(rig.scanner.configs)
        plan = service.plan(request=REQUEST)
        service.execute(plan_id=plan.plan_id, typed_confirmation=plan.confirm_phrase)
        spin_until(predicate=lambda: bool(outcomes))
        spin_until(predicate=lambda: len(rig.scanner.configs) == scans + 1)
        spin_for(seconds=0.15)

        assert [o.freed_bytes for o in outcomes[0]] == [FREED]
        assert [p.request.kind for p in executor.plans] == [ActionKind.CACHE_ITEM_REMOVE]
        assert len(rig.scanner.configs) == scans + 1
    finally:
        service.stop()


def test_a_refused_cache_item_removal_does_not_rescan() -> None:
    rig = _rig_with_item()
    service = disk_action_service(rig, FakeExecutor(error=TargetChanged()))
    rejected: list[str] = []
    service.connect("action-rejected", lambda _s, plan_id, _e: rejected.append(plan_id))
    try:
        scans = len(rig.scanner.configs)
        plan = service.plan(request=REQUEST)
        service.execute(plan_id=plan.plan_id, typed_confirmation=plan.confirm_phrase)
        spin_until(predicate=lambda: bool(rejected))
        spin_for(seconds=0.15)

        assert len(rig.scanner.configs) == scans
    finally:
        service.stop()


def test_freeing_selected_entries_rescans_the_disk() -> None:
    # F30: without the rescan the Disco page keeps the freed rows ticked on the old report.
    rig = _rig_with_item()
    executor = FreeingExecutor()
    service = disk_action_service(rig, executor)
    outcomes: list[tuple[StepOutcome, ...]] = []
    service.connect("action-finished", lambda _s, _p, o: outcomes.append(o))
    selected = selected_entry_id(kind=ActionKind.CACHE_ITEM_REMOVE, target_id=REQUEST.target_id)
    try:
        scans = len(rig.scanner.configs)
        request = ActionRequest(
            kind=ActionKind.DISK_FREE_SELECTED, selected_ids=frozenset({selected})
        )
        plan = service.plan(request=request)
        service.execute(plan_id=plan.plan_id, typed_confirmation=plan.confirm_phrase)
        spin_until(predicate=lambda: bool(outcomes))
        spin_until(predicate=lambda: len(rig.scanner.configs) == scans + 1)

        assert [p.request.kind for p in executor.plans] == [ActionKind.DISK_FREE_SELECTED]
        assert len(rig.scanner.configs) == scans + 1
    finally:
        service.stop()
