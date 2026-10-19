"""T-6.16: a cache with items is an expander of model sub-rows; the others stay plain rows."""

import pytest
from gi.repository import Adw, Gtk

from tests.core.disk_helpers import MB, report
from tests.ui.conftest import descendants
from wimm.model.cache_items import CacheItem, CacheRest
from wimm.model.disk import CacheEntry, CacheKind
from wimm.model.enums import CacheItemKind
from wimm.ui.disk_view import build_disk_sections
from wimm.ui.pages.disk_rows import build_disk_row
from wimm.ui.widgets import ACCESSIBLE_LABEL_ATTR

pytestmark = pytest.mark.ui
HF_PATH = "/home/u/.cache/huggingface/hub"


def _item(*, index: int) -> CacheItem:
    return CacheItem(
        id=f"models--org--m{index}",
        title=f"org/m{index}",
        path=f"{HF_PATH}/models--org--m{index}",
        size=(9 - index) * MB,
        st_ino=100 + index,
        st_dev=2049,
        kind=CacheItemKind.HF_MODEL,
    )


def _hf_entry() -> CacheEntry:
    items = tuple(_item(index=i) for i in range(5))
    return CacheEntry(
        kind=CacheKind.HUGGINGFACE,
        path=HF_PATH,
        size=sum(i.size for i in items) + 3 * MB,
        st_ino=11,
        st_dev=2049,
        items=items,
        rest=CacheRest(shared=0, unattributed=3 * MB),
    )


def _plain_entry() -> CacheEntry:
    return CacheEntry(kind=CacheKind.UV, path="/home/u/.cache/uv", size=MB, st_ino=12, st_dev=2049)


def _row(*, entry: CacheEntry) -> tuple[Adw.ActionRow | Adw.ExpanderRow, list[Gtk.Button]]:
    sections = build_disk_sections(report=report(caches=(entry,)), min_age_days=90)
    row = next(r for s in sections for r in s.rows if r.subtitle == entry.path)
    buttons: list[Gtk.Button] = []
    return build_disk_row(row=row, on_action=lambda _r: None, buttons=buttons), buttons


def _action_rows(*, widget: Gtk.Widget) -> list[Adw.ActionRow]:
    return [w for w in descendants(widget) if isinstance(w, Adw.ActionRow)]


def _button_labels(*, widget: Gtk.Widget) -> list[str]:
    return [(w.get_label() or "") for w in descendants(widget) if isinstance(w, Gtk.Button)]


def test_cache_with_items_is_an_expander_collapsed_by_default(display: None) -> None:
    widget, _buttons = _row(entry=_hf_entry())

    assert isinstance(widget, Adw.ExpanderRow)
    assert not widget.get_expanded()
    assert widget.get_subtitle().startswith(HF_PATH)


def test_expander_lists_five_models_and_unattributed(display: None) -> None:
    widget, _buttons = _row(entry=_hf_entry())

    titles = [r.get_title() for r in _action_rows(widget=widget)]
    assert [t for t in titles if t.startswith("org/")] == [f"org/m{i}" for i in range(5)]
    assert "Non attribuito" in titles


def test_cache_without_items_stays_a_plain_action_row(display: None) -> None:
    widget, _buttons = _row(entry=_plain_entry())

    assert isinstance(widget, Adw.ActionRow)
    assert not isinstance(widget, Adw.ExpanderRow)


def test_button_says_whole_cache_only_with_items(display: None) -> None:
    with_items, buttons_a = _row(entry=_hf_entry())
    _plain, buttons_b = _row(entry=_plain_entry())

    assert [b.get_label() for b in buttons_a] == ["Pulisci tutta la cache"]
    assert [b.get_label() for b in buttons_b] == ["Pulisci cache"]
    assert _button_labels(widget=with_items) == ["Pulisci tutta la cache"]


def test_sub_rows_have_no_button(display: None) -> None:
    widget, buttons = _row(entry=_hf_entry())

    assert len(buttons) == 1  # the cache's own; sub-rows add none
    assert len(_button_labels(widget=widget)) == 1  # expander toggle is not a Gtk.Button label


def test_expander_toggles(display: None) -> None:
    widget, _buttons = _row(entry=_hf_entry())

    assert isinstance(widget, Adw.ExpanderRow)
    widget.set_expanded(True)
    assert widget.get_expanded()
    widget.set_expanded(False)
    assert not widget.get_expanded()


def test_accessible_names(display: None) -> None:
    widget, _buttons = _row(entry=_hf_entry())

    name = getattr(widget, ACCESSIBLE_LABEL_ATTR)
    assert HF_PATH in name
    assert "Hugging Face" in name or widget.get_title() in name
    sub = next(r for r in _action_rows(widget=widget) if r.get_title() == "org/m0")
    sub_name = getattr(sub, ACCESSIBLE_LABEL_ATTR)
    assert sub_name.startswith("org/m0. 9 MB")
