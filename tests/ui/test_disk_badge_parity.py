from pathlib import Path

from tests.core.planning_helpers import NOW, OWNER_UID, snapshot
from wimm.core.disk_wire import disk_report_from_json
from wimm.core.planning import PlanningContext, plan_action
from wimm.model.actions import ActionRequest
from wimm.model.enums import ActionKind, TargetId
from wimm.ui.disk_view import build_disk_sections

SAMPLE = Path(__file__).parents[1] / "fixtures" / "disk_report_sample.json"
MIN_AGE = 90


def test_every_row_badge_equals_the_risk_of_the_plan_its_button_opens() -> None:
    # Container rows are planned from the snapshot, not the report: covered by click-through.
    report = disk_report_from_json(text=SAMPLE.read_text(encoding="utf-8"))
    context = PlanningContext(owner_uid=OWNER_UID, now=lambda: NOW, disk_report=report)
    rows = [
        row
        for section in build_disk_sections(report=report, min_age_days=MIN_AGE)
        for row in section.rows
        if row.action_kind is not None and row.action_kind is not ActionKind.CONTAINER_REMOVE
    ]
    checked = set()
    for row in rows:
        assert row.action_kind is not None
        target = TargetId(row.target_id) if row.target_id is not None else None
        request = ActionRequest(kind=row.action_kind, target_id=target)
        plan = plan_action(request=request, snapshot=snapshot(), context=context)
        assert plan.risk is row.risk, row.title
        checked.add(row.action_kind)

    assert {ActionKind.IMAGE_REMOVE, ActionKind.VOLUME_REMOVE, ActionKind.CACHE_CLEAN} <= checked
