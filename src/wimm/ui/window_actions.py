from typing import cast

import gi

from wimm.ui.action_flow import ActionFlow, ActionSource, can_act
from wimm.ui.pages.overview import OverviewPage
from wimm.ui.toasts import ToastNotifier
from wimm.ui.window_state import SnapshotSource

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk


def build_action_flow(
    *, parent: Gtk.Widget, source: SnapshotSource, toasts: Adw.ToastOverlay, overview: OverviewPage
) -> ActionFlow | None:
    """The flow behind the action buttons, or None when ``source`` cannot plan actions."""
    if not can_act(source=source):
        return None
    return ActionFlow(
        source=cast(ActionSource, source),
        parent=parent,
        notify=ToastNotifier(overlay=toasts),
        on_busy=lambda busy: overview.set_busy(busy=busy),
    )
