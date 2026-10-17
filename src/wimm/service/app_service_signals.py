from typing import Any

from gi.repository import GObject

# Emitted after consecutive_failures was incremented: "cycle-failed".
# "action-finished" is (plan_id, tuple[StepOutcome, ...]): every step ran, successfully or
# not. "action-rejected" is (plan_id, WimmError): the plan was refused before any step ran;
# errors raised by a step come back as a `failed` outcome in `action-finished`.
# "reclaim-measured" is (plan_id, ReclaimDelta), measured on a sample taken after the
# measuring delay.
_PLAN_AND_PAYLOAD = (GObject.TYPE_STRING, GObject.TYPE_PYOBJECT)

APP_SERVICE_SIGNALS: dict[str, Any] = {
    "snapshot-updated": (GObject.SignalFlags.RUN_LAST, None, ()),
    "cycle-failed": (GObject.SignalFlags.RUN_LAST, None, ()),
    "action-finished": (GObject.SignalFlags.RUN_LAST, None, _PLAN_AND_PAYLOAD),
    "action-rejected": (GObject.SignalFlags.RUN_LAST, None, _PLAN_AND_PAYLOAD),
    "reclaim-measured": (GObject.SignalFlags.RUN_LAST, None, _PLAN_AND_PAYLOAD),
}
