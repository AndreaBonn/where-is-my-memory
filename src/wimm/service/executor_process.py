"""Process termination (SPECIFICHE 8.4): SIGTERM to the tree, never an automatic SIGKILL."""

import signal
from dataclasses import dataclass

from .control_protocols import ProcessControl, StepOutcome, StepStatus
from .errors import ControlFailed, WimmError
from .executor_checks import ProcessRules, check_protection


@dataclass(frozen=True, slots=True, kw_only=True)
class TerminationRequest:
    order: int
    pid: int
    timeout_s: float
    rules: ProcessRules


def _signal_all(*, control: ProcessControl, pids: list[int]) -> list[str]:
    failures: list[str] = []
    for pid in pids:
        try:
            control.send_signal(pid=pid, sig=signal.SIGTERM)
        except ControlFailed as error:
            failures.append(error.message)
    return failures


def _live_descendants(*, control: ProcessControl, request: TerminationRequest) -> list[int]:
    """Deepest-first descendants, each checked like the root; one bad one rejects the tree."""
    pids: list[int] = []
    for pid in reversed(control.descendants(pid=request.pid)):
        live = control.inspect(pid=pid)
        if live is None:
            continue
        check_protection(live=live, rules=request.rules)
        pids.append(pid)
    return pids


def terminate_tree(*, control: ProcessControl, request: TerminationRequest) -> StepOutcome:
    """Check each descendant, SIGTERM them deepest first then the root, wait for the tree.

    Wrappers such as `npm` do not forward signals, hence the children go first. A process
    still alive after the timeout makes the outcome `not_responding`: forcing it is a
    separate, separately planned action.
    """
    try:
        pids = [*_live_descendants(control=control, request=request), request.pid]
    except WimmError as error:
        return StepOutcome(order=request.order, status=StepStatus.FAILED, message=error.message)
    failures = _signal_all(control=control, pids=pids)
    if failures:
        message = "; ".join(failures)
        return StepOutcome(order=request.order, status=StepStatus.FAILED, message=message)
    alive = control.wait_gone(pids=pids, timeout_s=request.timeout_s)
    if alive:
        listing = ", ".join(str(pid) for pid in sorted(alive))
        message = f"still running after {request.timeout_s:g}s: {listing}"
        return StepOutcome(order=request.order, status=StepStatus.NOT_RESPONDING, message=message)
    return StepOutcome(order=request.order, status=StepStatus.DONE)


def close_root(*, control: ProcessControl, request: TerminationRequest) -> StepOutcome:
    """SIGTERM the main process of an app and wait for it; its children get no signal.

    A browser or desktop app closes its own processes and saves its session (8.4), so
    the tree is neither listed nor signalled. A root still alive after the timeout is
    `not_responding`, same as `terminate_tree`.
    """
    failures = _signal_all(control=control, pids=[request.pid])
    if failures:
        message = "; ".join(failures)
        return StepOutcome(order=request.order, status=StepStatus.FAILED, message=message)
    if control.wait_gone(pids=[request.pid], timeout_s=request.timeout_s):
        message = f"still running after {request.timeout_s:g}s: {request.pid}"
        return StepOutcome(order=request.order, status=StepStatus.NOT_RESPONDING, message=message)
    return StepOutcome(order=request.order, status=StepStatus.DONE)
