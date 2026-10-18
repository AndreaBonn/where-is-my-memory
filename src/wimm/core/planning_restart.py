"""C4: «Riaccendi» starts again the containers a recent stop plan stopped. Pure."""

import shlex
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from wimm.i18n import _
from wimm.model.actions import ActionRequest, ContainerFingerprint
from wimm.model.enums import ActionKind, Risk
from wimm.model.errors import InvalidRequest

from .planning_drafts import Draft
from .risk import RiskAssessment
from .risk_table import CONSEQUENCES, ConsequenceKey

# What Docker reports for a container that `docker stop` stopped.
STOPPED_STATUS = "exited"


@dataclass(frozen=True, slots=True, kw_only=True)
class StoppedContainer:
    """A container a plan stopped: its id and the label the plan showed for it."""

    id: str
    label: str


@dataclass(frozen=True, slots=True, kw_only=True)
class StoppedProcess:
    """F14: a process a plan stopped, with the command it ran as the plan saw it."""

    label: str
    argv: tuple[str, ...]
    cwd: str | None


# Unicode categories a pasted command must not hold (S11): controls (Cc, C1 included), format
# characters such as bidi overrides and zero-width spaces (Cf), line and paragraph separators
# (Zl, Zp). They end the line, drive a terminal, or make the text look unlike what it runs.
FORBIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp"})


def _has_forbidden_character(text: str) -> bool:
    return any(unicodedata.category(char) in FORBIDDEN_CATEGORIES for char in text)


def restart_command(*, argv: Sequence[str] | None, cwd: str | None) -> str | None:
    """`cd -- <cwd> && <argv>` for a POSIX shell, or None when it cannot be built safely.

    None when argv or cwd is missing or empty, or when either holds a control, format or
    line-separator character: pasted or read, it would not be the one command shown.
    """
    if not argv or not cwd:
        return None
    if any(_has_forbidden_character(part) for part in (cwd, *argv)):
        return None
    return " ".join(("cd", "--", shlex.quote(cwd), "&&", shlex.join(argv)))


def _start_assessment() -> RiskAssessment:
    consequence = _(CONSEQUENCES[ConsequenceKey.START])
    return RiskAssessment(level=Risk.SAFE, consequences=(consequence,))


def plan_restart(
    *, request: ActionRequest, stopped: Mapping[str, tuple[StoppedContainer, ...]]
) -> list[Draft]:
    """One start per container the plan `request.target_id` stopped.

    Starting what the user stopped a moment ago gives back the state they had: safe,
    nothing is freed. The executor rechecks each container, so one started or removed
    in the meantime is left alone.

    Raises
    ------
    InvalidRequest
        If the plan is unknown, too old to be remembered, or stopped no container.
    """
    containers = stopped.get(request.target_id or "", ())
    if not containers:
        raise InvalidRequest(f"Plan {request.target_id} stopped no container to start again")
    assessed = _start_assessment()
    return [
        Draft(
            owner_ids=frozenset({item.id}),
            kind=ActionKind.CONTAINER_START,
            label=item.label,
            name=item.label,
            fingerprint=ContainerFingerprint(id=item.id, status=STOPPED_STATUS),
            assessed=assessed,
            reclaim_ram=0,
        )
        for item in containers
    ]
