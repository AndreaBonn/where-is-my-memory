"""Plain-language texts for non-expert users: why a program counts as unused, what it is."""

from datetime import datetime

from wimm.core.text import AT_LEAST_MARK, NO_CONNECTIONS_MARK, OBSERVING_PREFIX, spoken_duration
from wimm.i18n import N_, _
from wimm.model.enums import ActivityState, Category
from wimm.model.snapshot import ActivityAssessment, Group, Member, ProcessMember

ACTIVE_TEXT = N_("Lo stai usando adesso.")
OBSERVING_TEXT = N_("Lo stiamo osservando: tra poco sappiamo se lo usi.")
UNKNOWN_TEXT = N_("Non sappiamo se lo stai usando: decidi tu se chiuderlo.")
NOBODY_CONNECTS = N_(": nessuno ci si collega.")
# P11: names of use for common images and servers. Generic runtimes (node, python) are
# absent on purpose: the name would say nothing about what the program does.
IMAGE_NAMES = (
    ("keycloak", N_("Accesso utenti")),
    ("postgres", N_("Database")),
    ("postgresql", N_("Database")),
    ("mysql", N_("Database")),
    ("mariadb", N_("Database")),
    ("mongo", N_("Database")),
    ("mongodb", N_("Database")),
    ("redis", N_("Memoria veloce (cache)")),
    ("valkey", N_("Memoria veloce (cache)")),
    ("nginx", N_("Server web")),
    ("traefik", N_("Instradamento web")),
    ("rabbitmq", N_("Coda di messaggi")),
    ("kafka", N_("Coda di messaggi")),
    ("minio", N_("Archivio file")),
    ("elasticsearch", N_("Motore di ricerca")),
    ("opensearch", N_("Motore di ricerca")),
    ("ollama", N_("Modelli AI locali")),
    ("grafana", N_("Cruscotti")),
    ("prometheus", N_("Raccolta metriche")),
)
PROCESS_NAMES = (
    ("uvicorn", N_("Server web")),
    ("gunicorn", N_("Server web")),
    ("flask", N_("Server web")),
    ("vite", N_("Server dell'interfaccia")),
    ("webpack", N_("Server dell'interfaccia")),
    ("jupyter", N_("Quaderni Jupyter")),
    ("celery", N_("Lavori in background")),
    ("ollama", N_("Modelli AI locali")),
    ("kubectl", N_("Collegamento a Kubernetes")),
    # The git status daemon of the zsh prompt (powerlevel10k): one per open terminal.
    ("gitstatusd", N_("Stato git del terminale")),
)
# F10: programs that come back by themselves, and how; measured on gitstatusd 2026-10-19,
# whose zsh does not restart it while a new terminal starts its own.
PROCESS_RESTARTS = (
    (
        "gitstatusd",
        N_(
            "Lo stato git del terminale: riparte da solo nei terminali che apri dopo; "
            "in quelli già aperti torna quando li riapri."
        ),
    ),
)
NAME_SEPARATORS = "-_."


def plain_reason(*, activity: ActivityAssessment, now: datetime) -> str:
    """P7: one sentence on why a program counts as unused, in use or unknown."""
    if activity.state is ActivityState.ACTIVE:
        return _(ACTIVE_TEXT)
    if activity.state is not ActivityState.IDLE:
        observing = activity.reason.startswith(_(OBSERVING_PREFIX))
        return _(OBSERVING_TEXT) if observing else _(UNKNOWN_TEXT)
    # An idle assessment always carries its start (ActivityAssessment validates it).
    since = activity.since or now
    span = spoken_duration(seconds=(now - since).total_seconds())
    # Only when the core judged connections (a server) does "nobody connects" hold.
    tail = _(NOBODY_CONNECTS) if _(NO_CONNECTIONS_MARK) in activity.reason else "."
    # Idle since the monitor started is a lower bound, and the sentence says so.
    if _(AT_LEAST_MARK) in activity.reason:
        return _("Non lo usi da almeno {span}{tail}").format(span=span, tail=tail)
    return _("Non lo usi da {span}{tail}").format(span=span, tail=tail)


def titled_name(*, name: str, friendly: str | None) -> str:
    """P11/C2: the name of use first, the technical name in brackets."""
    return name if friendly is None else f"{friendly} ({name})"


def friendly_container_name(*, image: str) -> str | None:
    """The name of use of a container from its image, None when the image is not known.

    Only the exact image name counts: "kafka-ui" or "mongo-express" are tools around a
    service, not the service.
    """
    last = image.lower().rsplit("/", 1)[-1]
    repository = last.split(":", 1)[0]
    return next((_(name) for key, name in IMAGE_NAMES if key == repository), None)


def friendly_process_name(*, name: str) -> str | None:
    """The name of use of a process from its name, None for unknown or generic names."""
    head = _name_head(name=name)
    return next((_(label) for key, label in PROCESS_NAMES if head == key), None)


def restart_hint(*, name: str) -> str | None:
    """F10: how a program that restarts by itself comes back; None for the others."""
    head = _name_head(name=name)
    return next((_(text) for key, text in PROCESS_RESTARTS if head == key), None)


def _name_head(*, name: str) -> str:
    """The part of a name before any separator: gitstatusd-linux-x86_64 gives gitstatusd."""
    head = name.lower()
    for separator in NAME_SEPARATORS:
        head = head.split(separator, 1)[0]
    return head


def group_title(*, group: Group) -> str:
    """F7: a group that is one named program reads with its name of use first.

    Only when every member is that program (one gitstatusd per terminal makes several),
    and never for a project: a project called "vite" or "ollama" keeps its own name.
    """
    named = all(
        isinstance(member, ProcessMember) and member.name == group.name for member in group.members
    )
    # A project keeps its own name even when its only process shares it.
    if not group.members or not named or group.category is Category.PROJECT:
        return group.name
    return titled_name(name=group.name, friendly=friendly_process_name(name=group.name))


def member_title(*, member: Member) -> str:
    """P11: a member's name of use first, from its process name or container image."""
    if isinstance(member, ProcessMember):
        friendly = friendly_process_name(name=member.name)
    else:
        friendly = friendly_container_name(image=member.image)
    return titled_name(name=member.name, friendly=friendly)
