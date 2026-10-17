"""Fake `ComposeControl` and hand-built compose plans. Nothing here touches the system."""

from dataclasses import dataclass, field

from tests.service.executor_fakes import make_plan
from wimm.model.actions import ComposeFingerprint, Plan, PlanStep
from wimm.model.enums import ActionKind, Risk
from wimm.service.errors import ControlFailed

PROJECT = "wimmtest-demo"


@dataclass(slots=True)
class FakeCompose:
    """Per project, the container ids that exist; `down` empties the project."""

    projects: dict[str, frozenset[str]] = field(default_factory=dict)
    after_listing: dict[str, frozenset[str]] = field(default_factory=dict)
    failing: frozenset[str] = frozenset()
    calls: list[tuple[str, bool]] = field(default_factory=list)

    def container_ids(self, *, project: str) -> frozenset[str]:
        ids = self.projects.get(project, frozenset())
        if project in self.after_listing:
            self.projects[project] = self.after_listing.pop(project)
        return ids

    def down(self, *, project: str, volumes: bool) -> None:
        if project in self.failing:
            raise ControlFailed(f"compose down failed for {project}: no such network")
        self.calls.append((project, volumes))
        self.projects[project] = frozenset()


def compose_step(
    *,
    ids: frozenset[str],
    kind: ActionKind = ActionKind.COMPOSE_DOWN,
    project: str = PROJECT,
    order: int = 1,
) -> PlanStep:
    risk = Risk.DANGER if kind is ActionKind.COMPOSE_DOWN_VOLUMES else Risk.CAUTION
    return PlanStep(
        order=order,
        kind=kind,
        target_label=project,
        fingerprint=ComposeFingerprint(project=project, container_ids=ids),
        risk=risk,
    )


def compose_plan(
    *, ids: frozenset[str], kind: ActionKind = ActionKind.COMPOSE_DOWN, project: str = PROJECT
) -> Plan:
    return make_plan(steps=[compose_step(ids=ids, kind=kind, project=project)])
