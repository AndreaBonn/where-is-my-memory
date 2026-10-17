from dataclasses import dataclass
from pathlib import PurePosixPath
from types import MappingProxyType

from wimm.model.enums import Category

SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400
MINUTES_UP_TO_S = 2 * SECONDS_PER_HOUR
HOURS_UP_TO_S = 2 * SECONDS_PER_DAY

UNMEASURABLE_LABELS = MappingProxyType(
    {
        Category.BROWSER: "i browser",
        Category.DESKTOP_APP: "le app desktop",
        Category.TERMINAL: "i terminali",
    }
)


@dataclass(frozen=True, slots=True)
class IdleFacts:
    """Measured numbers behind an idle verdict.

    ``net_avg_bps`` is None when the entity has no network signal;
    ``open_port`` is the server port of a persistent connection, if any.
    """

    window_s: int
    cpu_avg_pct: float
    net_avg_bps: float | None
    watches_connections: bool
    open_port: int | None


def format_decimal(*, value: float) -> str:
    """Format with one decimal and the Italian comma, independent of the system locale."""
    return f"{value:.1f}".replace(".", ",")


def format_duration(*, seconds: float) -> str:
    """Format a duration as ``4 minuti``, ``3 h`` or ``2 giorni`` (floored, never zero)."""
    if seconds < SECONDS_PER_MINUTE:
        return "meno di 1 minuto"
    if seconds < MINUTES_UP_TO_S:
        minutes = int(seconds // SECONDS_PER_MINUTE)
        return f"{minutes} {'minuto' if minutes == 1 else 'minuti'}"
    if seconds < HOURS_UP_TO_S:
        return f"{int(seconds // SECONDS_PER_HOUR)} h"
    return f"{int(seconds // SECONDS_PER_DAY)} giorni"


def _counted(*, count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def spoken_duration(*, seconds: float) -> str:
    """Format a duration in whole words, ``40 minuti``, ``1 ora``, ``2 giorni`` (floored)."""
    if seconds < SECONDS_PER_MINUTE:
        return "meno di 1 minuto"
    if seconds < SECONDS_PER_HOUR:
        return _counted(count=int(seconds // SECONDS_PER_MINUTE), one="minuto", many="minuti")
    if seconds < SECONDS_PER_DAY:
        return _counted(count=int(seconds // SECONDS_PER_HOUR), one="ora", many="ore")
    return _counted(count=int(seconds // SECONDS_PER_DAY), one="giorno", many="giorni")


def reason_observing(*, elapsed_s: float) -> str:
    return f"in osservazione da {format_duration(seconds=elapsed_s)}"


def reason_unmeasurable(*, category: Category) -> str:
    label = UNMEASURABLE_LABELS.get(category)
    return "attività non misurabile" if label is None else f"attività non misurabile per {label}"


def reason_not_evaluated() -> str:
    return "attività non valutata per questa categoria"


def reason_cpu_unavailable() -> str:
    return "CPU non misurabile negli ultimi campioni"


def reason_active(*, active_for_s: float) -> str:
    return f"attività rilevata da {format_duration(seconds=active_for_s)}"


def _idle_detail(*, facts: IdleFacts) -> str:
    window = format_duration(seconds=facts.window_s)
    cpu = f"CPU media {format_decimal(value=facts.cpu_avg_pct)}%"
    if facts.watches_connections:
        connections = (
            "nessuna connessione nuova" if facts.open_port else "nessuna connessione in ingresso"
        )
        detail = f"{connections} e {cpu} negli ultimi {window}"
    elif facts.net_avg_bps is not None:
        net = f"traffico di rete medio {facts.net_avg_bps:.0f} B/s"
        detail = f"{cpu} e {net} negli ultimi {window}"
    else:
        detail = f"{cpu} negli ultimi {window}"
    if facts.open_port:
        detail += (
            "; c'è una connessione aperta da un browser "
            f"(probabile scheda dimenticata su localhost:{facts.open_port})"
        )
    return detail


def reason_idle(*, idle_for_s: float, facts: IdleFacts, from_monitor_start: bool) -> str:
    duration = format_duration(seconds=idle_for_s)
    if from_monitor_start:
        prefix = f"inattivo da almeno {duration}, cioè da quando il monitor è partito"
    else:
        prefix = f"inattivo da {duration}"
    return f"{prefix}; {_idle_detail(facts=facts)}"


def reason_foreground_idle(*, idle_for_s: float, window_s: float, from_monitor_start: bool) -> str:
    duration = format_duration(seconds=idle_for_s)
    if from_monitor_start:
        prefix = f"inattivo da almeno {duration}, cioè da quando il monitor è partito"
    else:
        prefix = f"inattivo da {duration}"
    return f"{prefix}; mai in primo piano negli ultimi {format_duration(seconds=window_s)}"


def reason_foreground_active(*, ago_s: float) -> str:
    return f"in primo piano {format_duration(seconds=ago_s)} fa"


def reason_idle_persisted(*, idle_for_s: float, observed_s: float) -> str:
    return (
        f"inattivo da {format_duration(seconds=idle_for_s)}; "
        "ultima attività registrata prima del riavvio, "
        f"in osservazione da {format_duration(seconds=observed_s)}"
    )


def reason_group_active(*, active: int, measurable: int) -> str:
    if measurable == 1:
        return "l'unico membro misurabile è attivo"
    noun = "membro attivo" if active == 1 else "membri attivi"
    return f"{active} {noun} su {measurable} misurabili"


def reason_group_idle(*, measurable: int) -> str:
    if measurable == 1:
        return "l'unico membro misurabile è inattivo"
    if measurable == 2:
        return "entrambi i membri misurabili sono inattivi"
    return f"tutti i {measurable} membri misurabili sono inattivi"


def reason_group_unknown(*, measurable: int) -> str:
    if measurable == 0:
        return "nessun membro misurabile"
    if measurable == 1:
        return "attività dell'unico membro misurabile ancora non determinata"
    return f"attività di almeno uno dei {measurable} membri misurabili ancora non determinata"


LAUNCHED_CATEGORIES = frozenset({Category.DEV_SERVER, Category.DEV_PROCESS, Category.AI_CLI})
PROTECTED_CATEGORIES = frozenset({Category.SYSTEM, Category.SESSION, Category.SELF})
MAX_LISTED_NAMES = 8
APP_TEMPLATES = MappingProxyType(
    {
        Category.BROWSER: "browser {name} con {processes} (schede, estensioni e servizi)",
        Category.DESKTOP_APP: "app desktop {name} con {processes}",
        Category.TERMINAL: "terminale {name} con {processes}, shell comprese",
    }
)
NOT_MODIFIABLE = "non modificabile da qui"
SINGLE_PORT_TEMPLATE = "in ascolto sulla porta {port}"
PORT_LIST_TEMPLATE = "in ascolto sulle porte {ports}"


@dataclass(frozen=True, slots=True)
class GroupFacts:
    """Measured facts a group explanation is built from (RF-08).

    ``folder`` is a full path: the project working directory for compose
    groups, the project root for processes launched from a terminal.
    """

    category: Category
    name: str
    folder: str | None
    containers: int
    processes: int
    ports: tuple[int, ...]
    compose_project: str | None
    lead_process: str | None
    process_names: tuple[str, ...] = ()


def _count_processes(*, count: int, lead: str | None) -> str:
    if count == 1:
        return f"un processo {lead}" if lead else "un processo"
    return f"{count} processi"


def _ports_phrase(*, ports: tuple[int, ...]) -> str:
    if len(ports) == 1:
        return SINGLE_PORT_TEMPLATE.format(port=ports[0])
    labels = [str(port) for port in ports]
    joined = f"{', '.join(labels[:-1])} e {labels[-1]}"
    return PORT_LIST_TEMPLATE.format(ports=joined)


def _with_ports(*, sentence: str, ports: tuple[int, ...]) -> str:
    return f"{sentence}, {_ports_phrase(ports=ports)}" if ports else sentence


def _launched_from_terminal(*, processes: int) -> str:
    return "lanciato" if processes == 1 else "lanciati"


def _in_folder(*, folder: str | None) -> str:
    return "" if folder is None else f" in {folder}"


def _explain_container(*, facts: GroupFacts) -> str:
    if facts.compose_project is None:
        return f"container '{facts.name}' senza progetto compose"
    return (
        f"progetto compose '{facts.compose_project}' con {facts.containers} container"
        f"{_in_folder(folder=facts.folder)}"
    )


def _explain_project(*, facts: GroupFacts) -> str:
    base = (
        f"{_explain_container(facts=facts)}, più "
        f"{_count_processes(count=facts.processes, lead=facts.lead_process)} "
        "nella stessa cartella"
    )
    return _with_ports(sentence=base, ports=facts.ports)


def _named_folder(*, folder: str | None) -> str:
    if folder is None:
        return ""
    return f" nella cartella {PurePosixPath(folder).name or folder}"


def _explain_launched(*, facts: GroupFacts) -> str:
    sentence = _count_processes(count=facts.processes, lead=facts.lead_process)
    folder = _named_folder(folder=facts.folder)
    if facts.category is Category.DEV_SERVER:
        ports = f" {_ports_phrase(ports=facts.ports)}" if facts.ports else ""
        return sentence + ports + folder
    launched = _launched_from_terminal(processes=facts.processes)
    return _with_ports(sentence=f"{sentence} {launched} dal terminale{folder}", ports=facts.ports)


def _names_phrase(*, names: tuple[str, ...]) -> str:
    distinct = sorted(set(names))
    shown = ", ".join(distinct[:MAX_LISTED_NAMES])
    hidden = len(distinct) - MAX_LISTED_NAMES
    return f"{shown} e altri {hidden}" if hidden > 0 else shown


def _explain_other(*, facts: GroupFacts) -> str:
    processes = _count_processes(count=facts.processes, lead=facts.lead_process)
    agreement = "riconducibile" if facts.processes == 1 else "riconducibili"
    return f"{processes} non {agreement} a un progetto o a un'app"


def explain_group(*, facts: GroupFacts) -> str:
    """Describe in Italian why a group exists and what is in it (RF-08).

    Parameters
    ----------
    facts : GroupFacts
        Category, counts, folder and listening ports of the group.
    """
    category = facts.category
    processes = _count_processes(count=facts.processes, lead=None)
    if category is Category.PROJECT:
        return _explain_project(facts=facts)
    if category is Category.CONTAINER:
        return _explain_container(facts=facts)
    if category in LAUNCHED_CATEGORIES:
        return _explain_launched(facts=facts)
    if category in APP_TEMPLATES:
        return APP_TEMPLATES[category].format(name=facts.name, processes=processes)
    if category in PROTECTED_CATEGORIES:
        return f"{facts.name}: {_names_phrase(names=facts.process_names)}, {NOT_MODIFIABLE}"
    return _explain_other(facts=facts)
