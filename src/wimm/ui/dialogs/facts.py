"""C2/C3: what a confirmation says in plain words: the targets, and what happens to them."""

import os

from wimm.model.actions import (
    ContainerFingerprint,
    DirFingerprint,
    ImageFingerprint,
    Plan,
    PlanStep,
    ProcessFingerprint,
)
from wimm.model.enums import ActionKind
from wimm.model.snapshot import Member, ProcessMember, Snapshot
from wimm.ui.format import format_size
from wimm.ui.plain import friendly_container_name, friendly_process_name, titled_name

WHAT_TITLE = "Cosa succede"
KEEP_TITLE = "Cosa resta"
RESTART_TITLE = "Per riaccenderlo"
KEEP_TEXT = "I file salvati, i dati e le impostazioni."
CONTAINER_RESTART = (
    "I contenitori: con «Riaccendi» nel messaggio che compare dopo, se tutto va a buon fine."
)
PROCESS_RESTART = "I programmi del terminale: con lo stesso comando, nella cartella {cwd}."
PROCESS_RESTART_NO_CWD = "I programmi del terminale: con lo stesso comando di prima."
APP_RESTART = "Le applicazioni: dal menu delle applicazioni, come al solito."
BUILD_CACHE_LABEL = "Cache di build Docker"
UNNAMED_IMAGE = "Immagine senza nome ({short})"
SHORT_ID_CHARS = 12
# Stops keep everything on disk; removals and cleanups do not.
KEEP_KINDS = frozenset(
    {ActionKind.PROCESS_TERMINATE, ActionKind.APP_CLOSE, ActionKind.CONTAINER_STOP}
)
LINE_SEPARATOR = "\n"
FIELD_SEPARATOR = " · "

Fact = tuple[str, str]


def members_by_id(*, snapshot: Snapshot | None) -> dict[str, Member]:
    """Every member of the snapshot by pid (as text) or container id."""
    found: dict[str, Member] = {}
    for group in () if snapshot is None else snapshot.groups:
        for member in group.members:
            key = str(member.pid) if isinstance(member, ProcessMember) else member.id
            found[key] = member
    return found


def _member_label(*, member: Member, sized: bool) -> str:
    if isinstance(member, ProcessMember):
        friendly = friendly_process_name(name=member.name)
    else:
        friendly = friendly_container_name(image=member.image)
    title = titled_name(name=member.name, friendly=friendly)
    if not sized:
        return title
    return f"{title}{FIELD_SEPARATOR}{format_size(size=member.memory.reclaimable)}"


def entry_label(*, step: PlanStep, members: dict[str, Member]) -> str:
    """C2: the name a non-expert recognises, the technical one in brackets."""
    fingerprint = step.fingerprint
    if isinstance(fingerprint, ProcessFingerprint | ContainerFingerprint):
        key = (
            str(fingerprint.pid) if isinstance(fingerprint, ProcessFingerprint) else fingerprint.id
        )
        member = members.get(key)
        # A start (C4) frees nothing: its entry carries no size.
        sized = step.kind is not ActionKind.CONTAINER_START
        return step.target_label if member is None else _member_label(member=member, sized=sized)
    if isinstance(fingerprint, ImageFingerprint) and step.target_label.startswith("sha256:"):
        return UNNAMED_IMAGE.format(short=fingerprint.id.removeprefix("sha256:")[:SHORT_ID_CHARS])
    if isinstance(fingerprint, DirFingerprint) and step.kind is ActionKind.CACHE_CLEAN:
        return f"Cache {os.path.basename(fingerprint.realpath)}"
    if step.kind is ActionKind.BUILDER_PRUNE:
        return BUILD_CACHE_LABEL
    return step.target_label


def _restart_lines(*, plan: Plan, members: dict[str, Member]) -> list[str]:
    kinds = {step.kind for step in plan.steps}
    lines = []
    if ActionKind.CONTAINER_STOP in kinds:
        lines.append(CONTAINER_RESTART)
    processes = [
        members.get(str(step.fingerprint.pid))
        for step in plan.steps
        if step.kind is ActionKind.PROCESS_TERMINATE
        and isinstance(step.fingerprint, ProcessFingerprint)
    ]
    if processes:
        first = processes[0]
        cwd = first.cwd if isinstance(first, ProcessMember) else None
        lines.append(PROCESS_RESTART.format(cwd=cwd) if cwd else PROCESS_RESTART_NO_CWD)
    if ActionKind.APP_CLOSE in kinds:
        lines.append(APP_RESTART)
    return lines


def facts_for(*, plan: Plan, snapshot: Snapshot | None) -> tuple[Fact, ...]:
    """C3: "Cosa succede", then for stops "Cosa resta" and "Per riaccenderlo"."""
    facts: list[Fact] = []
    if plan.consequences:
        facts.append((WHAT_TITLE, LINE_SEPARATOR.join(plan.consequences)))
    if {step.kind for step in plan.steps} <= KEEP_KINDS:
        facts.append((KEEP_TITLE, KEEP_TEXT))
        restart = _restart_lines(plan=plan, members=members_by_id(snapshot=snapshot))
        if restart:
            facts.append((RESTART_TITLE, LINE_SEPARATOR.join(restart)))
    return tuple(facts)
