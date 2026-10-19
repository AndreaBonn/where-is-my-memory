"""T-6.24: a model sub-row carries the removal action; the rest rows stay without one."""

from dataclasses import replace

import pytest

from tests.core.disk_helpers import MB, report
from tests.core.planning_helpers import NOW, OWNER_UID, snapshot
from tests.ui.test_disk_items import _entry
from wimm.core.planning import PlanningContext, plan_action
from wimm.core.row_consequence import join_consequences
from wimm.model.actions import ActionRequest
from wimm.model.enums import ActionKind, CacheItemKind, PlanId, Risk, TargetId
from wimm.ui.disk_items import item_rows


def test_model_sub_row_has_the_removal_action_and_target() -> None:
    row = item_rows(entry=_entry(count=2)).rows[0]

    assert row.action_kind is ActionKind.CACHE_ITEM_REMOVE
    assert row.target_id == "huggingface:models--org--m0"
    assert row.risk is Risk.CAUTION
    assert row.risk_text and row.risk_style


@pytest.mark.parametrize("kind", list(CacheItemKind))
def test_sub_row_consequence_equals_the_dialog_text_for_every_item_kind(
    kind: CacheItemKind,
) -> None:
    entry = _entry(count=2)
    entry = replace(entry, items=tuple(replace(item, kind=kind) for item in entry.items))
    row = item_rows(entry=entry).rows[1]
    assert row.action_kind is not None and row.target_id is not None
    context = PlanningContext(
        owner_uid=OWNER_UID,
        now=lambda: NOW,
        new_plan_id=lambda: PlanId("p"),
        disk_report=report(caches=(entry,)),
        which=lambda name: f"/usr/bin/{name}",
    )

    plan = plan_action(
        request=ActionRequest(kind=row.action_kind, target_id=TargetId(row.target_id)),
        snapshot=snapshot(),
        context=context,
    )

    assert row.consequence
    assert row.consequence == join_consequences(consequences=plan.consequences)


def test_rest_rows_have_no_action_while_models_have_one() -> None:
    view = item_rows(entry=_entry(count=2, shared=MB, unattributed=MB))
    models, rest = view.rows[:2], view.rows[2:]

    assert all(row.action_kind is ActionKind.CACHE_ITEM_REMOVE for row in models)
    assert len(rest) == 2
    assert all(
        (row.action_kind, row.target_id, row.risk, row.risk_text, row.consequence)
        == (None, None, None, None, "")
        for row in rest
    )
