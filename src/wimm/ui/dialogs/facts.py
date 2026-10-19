"""C2/C3: what a confirmation says in plain words: the targets, and what happens to them."""

from wimm.i18n import N_, _
from wimm.model.actions import (
    ContainerFingerprint,
    ImageFingerprint,
    Plan,
    PlanStep,
    ProcessFingerprint,
)
from wimm.model.enums import ActionKind
from wimm.model.snapshot import Member, ProcessMember, Snapshot
from wimm.ui.format import format_size
from wimm.ui.plain import (
    friendly_container_name,
    friendly_process_name,
    restart_hint,
    titled_name,
)

WHAT_TITLE = N_("Cosa succede")
KEEP_TITLE = N_("Cosa resta")
RESTART_TITLE = N_("Per riaccenderlo")
KEEP_TEXT = N_("I file salvati, i dati e le impostazioni.")
CONTAINER_RESTART = N_(
    "I contenitori: con «Riaccendi» nel messaggio che compare dopo, se tutto va a buon fine."
)
PROCESS_RESTART = N_("I programmi del terminale: con lo stesso comando, nella cartella {cwd}.")
PROCESS_RESTART_NO_CWD = N_("I programmi del terminale: con lo stesso comando di prima.")
APP_RESTART = N_("Le applicazioni: dal menu delle applicazioni, come al solito.")
BUILD_CACHE_LABEL = N_("Cache di build Docker")
UNNAMED_IMAGE = N_("Immagine senza nome ({short})")
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
        short = fingerprint.id.removeprefix("sha256:")[:SHORT_ID_CHARS]
        return _(UNNAMED_IMAGE).format(short=short)
    if step.kind is ActionKind.BUILDER_PRUNE:
        return _(BUILD_CACHE_LABEL)
    return step.target_label


def _shared_cwd(*, members: list[Member | None]) -> str | None:
    """The folder every process runs in; None when one differs, is unknown or is unreadable."""
    cwds = {member.cwd if isinstance(member, ProcessMember) else None for member in members}
    return cwds.pop() if len(cwds) == 1 else None


def _restart_lines(*, plan: Plan, members: dict[str, Member]) -> list[str]:
    kinds = {step.kind for step in plan.steps}
    lines = []
    if ActionKind.CONTAINER_STOP in kinds:
        lines.append(_(CONTAINER_RESTART))
    processes = [
        members.get(str(step.fingerprint.pid))
        for step in plan.steps
        if step.kind is ActionKind.PROCESS_TERMINATE
        and isinstance(step.fingerprint, ProcessFingerprint)
    ]
    hints = [restart_hint(name=m.name) if isinstance(m, ProcessMember) else None for m in processes]
    # One line per program that comes back by itself, however many copies stop.
    lines.extend(dict.fromkeys(hint for hint in hints if hint is not None))
    plain = [member for member, hint in zip(processes, hints, strict=True) if hint is None]
    if plain:
        cwd = _shared_cwd(members=plain)
        lines.append(_(PROCESS_RESTART).format(cwd=cwd) if cwd else _(PROCESS_RESTART_NO_CWD))
    if ActionKind.APP_CLOSE in kinds:
        lines.append(_(APP_RESTART))
    return lines


def facts_for(*, plan: Plan, snapshot: Snapshot | None) -> tuple[Fact, ...]:
    """C3: "Cosa succede", then for stops "Cosa resta" and "Per riaccenderlo"."""
    facts: list[Fact] = []
    if plan.consequences:
        facts.append((_(WHAT_TITLE), LINE_SEPARATOR.join(plan.consequences)))
    if {step.kind for step in plan.steps} <= KEEP_KINDS:
        facts.append((_(KEEP_TITLE), _(KEEP_TEXT)))
        restart = _restart_lines(plan=plan, members=members_by_id(snapshot=snapshot))
        if restart:
            facts.append((_(RESTART_TITLE), LINE_SEPARATOR.join(restart)))
    return tuple(facts)
