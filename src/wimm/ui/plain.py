"""Plain-language texts for non-expert users: why a program counts as unused, what it is."""

from datetime import datetime

from wimm.core.text import AT_LEAST_MARK, NO_CONNECTIONS_MARK, OBSERVING_PREFIX, spoken_duration
from wimm.model.enums import ActivityState
from wimm.model.snapshot import ActivityAssessment

ACTIVE_TEXT = "Lo stai usando adesso."
OBSERVING_TEXT = "Lo stiamo osservando: tra poco sappiamo se lo usi."
UNKNOWN_TEXT = "Non sappiamo se lo stai usando: decidi tu se chiuderlo."
NOBODY_CONNECTS = ": nessuno ci si collega."
# P11: names of use for common images and servers. Generic runtimes (node, python) are
# absent on purpose: the name would say nothing about what the program does.
IMAGE_NAMES = (
    ("keycloak", "Accesso utenti"),
    ("postgres", "Database"),
    ("postgresql", "Database"),
    ("mysql", "Database"),
    ("mariadb", "Database"),
    ("mongo", "Database"),
    ("mongodb", "Database"),
    ("redis", "Memoria veloce (cache)"),
    ("valkey", "Memoria veloce (cache)"),
    ("nginx", "Server web"),
    ("traefik", "Instradamento web"),
    ("rabbitmq", "Coda di messaggi"),
    ("kafka", "Coda di messaggi"),
    ("minio", "Archivio file"),
    ("elasticsearch", "Motore di ricerca"),
    ("opensearch", "Motore di ricerca"),
    ("ollama", "Modelli AI locali"),
    ("grafana", "Cruscotti"),
    ("prometheus", "Raccolta metriche"),
)
PROCESS_NAMES = (
    ("uvicorn", "Server web"),
    ("gunicorn", "Server web"),
    ("flask", "Server web"),
    ("vite", "Server dell'interfaccia"),
    ("webpack", "Server dell'interfaccia"),
    ("jupyter", "Quaderni Jupyter"),
    ("celery", "Lavori in background"),
    ("ollama", "Modelli AI locali"),
    ("kubectl", "Collegamento a Kubernetes"),
)
NAME_SEPARATORS = "-_."


def plain_reason(*, activity: ActivityAssessment, now: datetime) -> str:
    """P7: one sentence on why a program counts as unused, in use or unknown."""
    if activity.state is ActivityState.ACTIVE:
        return ACTIVE_TEXT
    if activity.state is not ActivityState.IDLE:
        return OBSERVING_TEXT if activity.reason.startswith(OBSERVING_PREFIX) else UNKNOWN_TEXT
    # An idle assessment always carries its start (ActivityAssessment validates it).
    since = activity.since or now
    span = spoken_duration(seconds=(now - since).total_seconds())
    # Only when the core judged connections (a server) does "nobody connects" hold.
    tail = NOBODY_CONNECTS if NO_CONNECTIONS_MARK in activity.reason else "."
    # Idle since the monitor started is a lower bound, and the sentence says so.
    at_least = "almeno " if AT_LEAST_MARK in activity.reason else ""
    return f"Non lo usi da {at_least}{span}{tail}"


def friendly_container_name(*, image: str) -> str | None:
    """The name of use of a container from its image, None when the image is not known.

    Only the exact image name counts: "kafka-ui" or "mongo-express" are tools around a
    service, not the service.
    """
    last = image.lower().rsplit("/", 1)[-1]
    repository = last.split(":", 1)[0]
    return next((name for key, name in IMAGE_NAMES if key == repository), None)


def friendly_process_name(*, name: str) -> str | None:
    """The name of use of a process from its name, None for unknown or generic names."""
    head = name.lower()
    for separator in NAME_SEPARATORS:
        head = head.split(separator, 1)[0]
    return next((label for key, label in PROCESS_NAMES if head == key), None)
