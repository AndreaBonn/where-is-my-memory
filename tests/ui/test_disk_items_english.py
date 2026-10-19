"""The sub-rows of a cache with items, in English."""

import pytest

from tests.ui.test_disk_items import _entry
from wimm.core.constants import CACHE_ITEMS_CAP
from wimm.ui.disk_items import item_rows

pytestmark = pytest.mark.usefixtures("english")
MB = 1_000_000


def test_item_rows_english_titles_and_counter() -> None:
    view = item_rows(entry=_entry(count=CACHE_ITEMS_CAP + 10, shared=MB, unattributed=MB))

    assert [row.title for row in view.rows[-2:]] == ["Shared between models", "Unattributed"]
    assert view.more_text == "and 10 more"


def test_item_rows_english_unattributed_sentence() -> None:
    view = item_rows(entry=_entry(count=1, unattributed=MB))

    assert view.rows[-1].subtitle == (
        "Files no model links to, lock files and files at the root of the cache. "
        "They are freed only by cleaning the whole cache."
    )
