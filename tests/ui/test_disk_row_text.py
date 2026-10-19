"""T-6.8: a Disco row shows the consequence under the path and names it for assistive tech."""

import pytest
from gi.repository import Adw

from wimm.model.enums import ActionKind, Risk
from wimm.ui.disk_model import DiskRowView
from wimm.ui.pages.disk_rows import build_disk_row
from wimm.ui.widgets import ACCESSIBLE_LABEL_ATTR

pytestmark = pytest.mark.ui
CONSEQUENCE = "Rimuove la cartella; si rigenera alla prossima build."
PATH = "/home/u/proj/node_modules"


def make_view(*, consequence: str, with_action: bool) -> DiskRowView:
    return DiskRowView(
        title="node_modules",
        subtitle=PATH,
        size_text="1,2 GB",
        risk=Risk.SAFE if with_action else None,
        risk_text="Sicuro" if with_action else None,
        risk_style="success" if with_action else None,
        action_kind=ActionKind.CACHE_CLEAN if with_action else None,
        consequence=consequence,
    )


def accessible_name(row: Adw.ActionRow) -> str | None:
    return getattr(row, ACCESSIBLE_LABEL_ATTR, None)


def test_row_with_action_shows_the_consequence_under_the_path(display: None) -> None:
    row = build_disk_row(row=make_view(consequence=CONSEQUENCE, with_action=True))

    assert row.get_subtitle() == f"{PATH}\n{CONSEQUENCE}"
    assert row.get_subtitle_lines() == 0  # no cap: never ellipsized (S4)


def test_row_with_action_names_itself_with_the_consequence(display: None) -> None:
    row = build_disk_row(row=make_view(consequence=CONSEQUENCE, with_action=True))

    name = accessible_name(row) or ""
    assert "node_modules" in name
    assert CONSEQUENCE in name


def test_row_without_action_has_no_consequence_line_and_a_plain_name(display: None) -> None:
    row = build_disk_row(row=make_view(consequence="", with_action=False))

    subtitle = row.get_subtitle()
    assert subtitle == PATH
    assert "\n" not in subtitle
    assert CONSEQUENCE not in (accessible_name(row) or "")
    assert "node_modules" in (accessible_name(row) or "")
