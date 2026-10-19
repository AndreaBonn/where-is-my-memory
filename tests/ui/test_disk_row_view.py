"""DiskRowView invariants: the "e altre N" counter only exists under item sub-rows (F10)."""

import pytest

from wimm.ui.disk_model import DiskRowView


def _sub_row() -> DiskRowView:
    return DiskRowView(title="org/m1", subtitle="/c/hub/models--org--m1", size_text="1 MB")


def test_items_more_without_items_is_rejected() -> None:
    with pytest.raises(ValueError, match="items_more"):
        DiskRowView(title="hf", subtitle="/c/hub", size_text="5 MB", items_more="e altre 3")


def test_items_more_with_items_is_accepted() -> None:
    row = DiskRowView(
        title="hf", subtitle="/c/hub", size_text="5 MB", items=(_sub_row(),), items_more="e altre 3"
    )

    assert row.items_more == "e altre 3"
