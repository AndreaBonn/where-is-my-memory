"""Member-level assembly: memory, risk target and offered actions (SPECIFICHE 5.3, 5.6)."""

from collections.abc import Mapping
from dataclasses import dataclass

from wimm.model.enums import Category
from wimm.model.memory import MemoryUse
from wimm.model.raw import RawContainer, RawProcess
from wimm.model.snapshot import ActionOffer, ActivityAssessment, ContainerMember, ProcessMember

from .categorize import CategoryDecision, has_documents, is_terminal_shell
from .memory import process_memory
from .risk import RiskTarget, available_actions

# `docker stop` works on all of these; anything else is not alive.
STOPPABLE_STATES = frozenset({"running", "paused", "restarting"})
UNKNOWN_CREATE_TIME = 0.0


@dataclass(frozen=True, slots=True)
class ProcessFacts:
    """A categorized process with its sampled ports and activity."""

    proc: RawProcess
    decision: CategoryDecision
    listen_ports: frozenset[int]
    activity: ActivityAssessment


def process_memory_use(*, proc: RawProcess) -> MemoryUse:
    """Return PSS with USS plus swap reclaimable, or RSS with nothing reclaimable.

    Without PSS (processes of other users are not readable) the figure is an RSS
    estimate that double-counts shared pages, and no part of it is called reclaimable.
    The model has no field to flag the estimate.

    Parameters
    ----------
    proc : RawProcess
        Collected measurements of one process.
    """
    if proc.pss is None:
        return MemoryUse(used=proc.rss, reclaimable=0)
    return process_memory(proc=proc)


def _process_target(
    *, facts: ProcessFacts, category: Category, desktop_categories: Mapping[str, tuple[str, ...]]
) -> RiskTarget:
    proc = facts.proc
    return RiskTarget(
        kind="process",
        category=category,
        activity=facts.activity.state,
        is_foreground_on_tty=proc.is_foreground,
        has_documents=has_documents(
            appid=facts.decision.appid, categories=desktop_categories, process_name=proc.name
        ),
        is_terminal_shell=is_terminal_shell(proc=proc),
        process_name=proc.name,
        cwd=proc.cwd,
    )


def _process_member(
    *, facts: ProcessFacts, category: Category, actions: tuple[ActionOffer, ...]
) -> ProcessMember:
    proc = facts.proc
    return ProcessMember(
        pid=proc.pid,
        create_time=UNKNOWN_CREATE_TIME if proc.create_time is None else proc.create_time,
        name=proc.name,
        cmdline=proc.cmdline or (),
        cwd=proc.cwd,
        category=category,
        listen_ports=tuple(sorted(facts.listen_ports)),
        memory=process_memory_use(proc=proc),
        activity=facts.activity,
        actions=actions,
    )


def build_process_member(
    *, facts: ProcessFacts, desktop_categories: Mapping[str, tuple[str, ...]]
) -> ProcessMember:
    """Build a process member with the actions allowed by its category and state.

    Parameters
    ----------
    facts : ProcessFacts
        Process, its categorization, LISTEN ports and activity verdict.
    desktop_categories : Mapping[str, tuple[str, ...]]
        Desktop `Categories` by appid, used to tell document apps from the rest.

    Raises
    ------
    ValueError
        If the categorization excluded the process: it must not reach a group.
    """
    category = facts.decision.category
    if category is None:
        raise ValueError(f"excluded process {facts.proc.pid} cannot be a group member")
    target = _process_target(facts=facts, category=category, desktop_categories=desktop_categories)
    # No start time, no fingerprint (spec 8.2): the action could hit a recycled pid.
    actions = () if facts.proc.create_time is None else available_actions(target=target)
    return _process_member(facts=facts, category=category, actions=actions)


def build_container_member(
    *, container: RawContainer, activity: ActivityAssessment
) -> ContainerMember:
    """Build a container member whose whole working set counts as reclaimable.

    Parameters
    ----------
    container : RawContainer
        Collected container with its working-set bytes.
    activity : ActivityAssessment
        Activity verdict computed from the container history.
    """
    target = RiskTarget(
        kind="container",
        category=Category.CONTAINER,
        activity=activity.state,
        is_running=container.state in STOPPABLE_STATES,
    )
    return ContainerMember(
        id=container.id,
        name=container.name,
        image=container.image,
        state=container.state,
        memory=MemoryUse(used=container.memory_bytes, reclaimable=container.memory_bytes),
        mounts=container.mounts,
        activity=activity,
        actions=available_actions(target=target),
    )
