"""F14: after stopping processes the toast offers to copy the command that restarts them."""

import pytest

from tests.ui.conftest import FakeActionService, WindowFactory, main_context_iterate
from tests.ui.test_window_outcome import button_labelled, confirmed, ready, shown
from wimm.model.enums import PlanId
from wimm.service.control_protocols import StepOutcome, StepStatus
from wimm.ui import action_flow
from wimm.ui.window import MainWindow

pytestmark = pytest.mark.ui
COPY = "Copia comando di riavvio"
WARNING = "Il comando può contenere password o token; resta copiato per un minuto."
FIRST = "cd /work/app && node server.js"
SECOND = "cd '/work/my app' && python3 -m http.server 8765"


def stop_processes(
    window_factory: WindowFactory, *, commands: tuple[str, ...]
) -> tuple[MainWindow, FakeActionService, PlanId]:
    window, service = ready(window_factory)
    plan = confirmed(window, service)
    service.commands[plan.plan_id] = commands
    outcomes = tuple(StepOutcome(order=s.order, status=StepStatus.DONE) for s in plan.steps)
    service.emit("action-finished", plan.plan_id, outcomes)
    main_context_iterate()
    return window, service, PlanId(plan.plan_id)


def test_the_toast_warns_about_secrets_before_offering_the_copy(
    window_factory: WindowFactory,
) -> None:
    window, _service, _plan_id = stop_processes(window_factory, commands=(FIRST,))

    shown(window, f"whitebox: arresto completato. {WARNING}")
    assert button_labelled(window, COPY) is not None


def test_copy_puts_one_command_per_line_on_the_clipboard(
    window_factory: WindowFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    copied: list[str] = []

    def fake_copy(*, text: str) -> bool:
        copied.append(text)
        return True

    monkeypatch.setattr(action_flow, "copy_to_clipboard", fake_copy)
    window, _service, _plan_id = stop_processes(window_factory, commands=(FIRST, SECOND))
    button = button_labelled(window, COPY)
    assert button is not None

    button.emit("clicked")

    assert copied == [f"{FIRST}\n{SECOND}"]
    shown(window, "Comando copiato")


def test_no_command_means_no_copy_button(window_factory: WindowFactory) -> None:
    window, _service, _plan_id = stop_processes(window_factory, commands=())

    shown(window, "whitebox: arresto completato")
    assert button_labelled(window, COPY) is None


def test_a_command_that_cannot_be_copied_shows_the_error_and_does_not_raise(
    window_factory: WindowFactory,
) -> None:
    surrogate = "cd -- /w && node \udcff"
    window, _service, _plan_id = stop_processes(window_factory, commands=(surrogate,))
    button = button_labelled(window, COPY)
    assert button is not None

    button.emit("clicked")

    shown(window, "Non riesco a copiare negli appunti")
