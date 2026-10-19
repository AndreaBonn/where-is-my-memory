"""T-6.24: a model sub-row carries the removal action; the rest rows stay without one."""

from tests.core.disk_helpers import MB, report
from tests.ui.test_disk_items import _entry
from wimm.core.planning_cache_item import plan_cache_item_remove
from wimm.model.actions import ActionRequest
from wimm.model.enums import ActionKind, Risk, TargetId
from wimm.ui.disk_items import item_rows


def test_model_sub_row_has_the_removal_action_and_target() -> None:
    row = item_rows(entry=_entry(count=2)).rows[0]

    assert row.action_kind is ActionKind.CACHE_ITEM_REMOVE
    assert row.target_id == "huggingface:models--org--m0"
    assert row.risk is Risk.CAUTION
    assert row.risk_text and row.risk_style


def test_model_sub_row_consequence_equals_the_plan_text() -> None:
    entry = _entry(count=2)
    row = item_rows(entry=entry).rows[1]

    assert row.action_kind is not None and row.target_id is not None
    drafts = plan_cache_item_remove(
        request=ActionRequest(kind=row.action_kind, target_id=TargetId(row.target_id)),
        report=report(caches=(entry,)),
    )

    assert row.consequence
    assert (row.consequence,) == drafts[0].assessed.consequences


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
