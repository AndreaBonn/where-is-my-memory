"""S3: the next safe step of a row is blue; an action that can lose something stays grey."""

from dataclasses import replace

import pytest

from tests.core.planning_helpers import group, proc, snapshot
from tests.ui.conftest import FakeActionService, WindowFactory, present_and_settle
from tests.ui.disk_page_helpers import buttons_in
from tests.ui.test_window_actions import primary_button
from wimm.model.enums import ActionKind, Risk
from wimm.model.snapshot import ActionOffer
from wimm.ui.disk_model import DiskRowView
from wimm.ui.pages.disk_rows import build_disk_row

pytestmark = pytest.mark.ui
SUGGESTED = "suggested-action"
GB = 1_000_000_000


@pytest.mark.parametrize(("risk", "blue"), [(Risk.SAFE, True), (Risk.CAUTION, False)])
def test_the_row_button_is_blue_only_when_nothing_is_lost(
    window_factory: WindowFactory, risk: Risk, blue: bool
) -> None:
    server = replace(
        group(gid="srv", name="whitebox", members=(proc(pid=1, reclaimable=GB),)),
        primary_action=ActionOffer(kind=ActionKind.GROUP_STOP, risk=risk),
    )
    window = window_factory(FakeActionService(snapshot=snapshot(server)))
    present_and_settle(window)

    assert primary_button(window).has_css_class(SUGGESTED) is blue


@pytest.mark.parametrize(("risk", "blue"), [(Risk.SAFE, True), (Risk.DANGER, False)])
def test_a_disk_row_button_is_blue_only_when_nothing_is_lost(
    display: None, risk: Risk, blue: bool
) -> None:
    row = DiskRowView(
        title="uv",
        subtitle="cache",
        size_text="1 MB",
        risk=risk,
        action_kind=ActionKind.CACHE_CLEAN,
        target_id="uv",
    )

    (button,) = buttons_in(build_disk_row(row=row, on_action=lambda _row: None))

    assert button.has_css_class(SUGGESTED) is blue


def test_the_color_follows_a_risk_that_changes_in_place(window_factory: WindowFactory) -> None:
    def with_risk(risk: Risk) -> FakeActionService:
        server = replace(
            group(gid="srv", name="whitebox", members=(proc(pid=1, reclaimable=GB),)),
            primary_action=ActionOffer(kind=ActionKind.GROUP_STOP, risk=risk),
        )
        return FakeActionService(snapshot=snapshot(server))

    service = with_risk(Risk.SAFE)
    window = window_factory(service)
    present_and_settle(window)
    assert primary_button(window).has_css_class(SUGGESTED)

    service.publish(with_risk(Risk.CAUTION).snapshot())
    present_and_settle(window)

    assert not primary_button(window).has_css_class(SUGGESTED)
