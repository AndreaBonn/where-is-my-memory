from dataclasses import dataclass
from pathlib import PurePosixPath
from types import MappingProxyType

from wimm.i18n import N_, _, ngettext
from wimm.model.enums import Category

LAUNCHED_CATEGORIES = frozenset({Category.DEV_SERVER, Category.DEV_PROCESS, Category.AI_CLI})
PROTECTED_CATEGORIES = frozenset({Category.SYSTEM, Category.SESSION, Category.SELF})
MAX_LISTED_NAMES = 8
APP_TEMPLATES = MappingProxyType(
    {
        Category.BROWSER: N_("browser {name} con {processes} (schede, estensioni e servizi)"),
        Category.DESKTOP_APP: N_("app desktop {name} con {processes}"),
        Category.TERMINAL: N_("terminale {name} con {processes}, shell comprese"),
    }
)
NOT_MODIFIABLE = N_("non modificabile da qui")
SINGLE_PORT_TEMPLATE = N_("in ascolto sulla porta {port}")
PORT_LIST_TEMPLATE = N_("in ascolto sulle porte {ports}")


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
    tool_reason: str | None = None


def _count_processes(*, count: int, lead: str | None) -> str:
    if count == 1:
        return _("un processo {lead}").format(lead=lead) if lead else _("un processo")
    return _("{count} processi").format(count=count)


def _ports_phrase(*, ports: tuple[int, ...]) -> str:
    if len(ports) == 1:
        return _(SINGLE_PORT_TEMPLATE).format(port=ports[0])
    labels = [str(port) for port in ports]
    joined = _("{head} e {last}").format(head=", ".join(labels[:-1]), last=labels[-1])
    return _(PORT_LIST_TEMPLATE).format(ports=joined)


def _with_ports(*, sentence: str, ports: tuple[int, ...]) -> str:
    return f"{sentence}, {_ports_phrase(ports=ports)}" if ports else sentence


def _with_folder(*, sentence: str, folder_phrase: str) -> str:
    return f"{sentence} {folder_phrase}" if folder_phrase else sentence


def _in_folder(*, folder: str | None) -> str:
    return "" if folder is None else _("in {folder}").format(folder=folder)


def _explain_container(*, facts: GroupFacts) -> str:
    if facts.compose_project is None:
        return _("container '{name}' senza progetto compose").format(name=facts.name)
    sentence = ngettext(
        "progetto compose '{project}' con {count} container",
        "progetto compose '{project}' con {count} container",
        facts.containers,
    ).format(project=facts.compose_project, count=facts.containers)
    return _with_folder(sentence=sentence, folder_phrase=_in_folder(folder=facts.folder))


def _explain_project(*, facts: GroupFacts) -> str:
    processes = _count_processes(count=facts.processes, lead=facts.lead_process)
    base = _("{container}, più {processes} nella stessa cartella").format(
        container=_explain_container(facts=facts), processes=processes
    )
    return _with_ports(sentence=base, ports=facts.ports)


def _named_folder(*, folder: str | None) -> str:
    if folder is None:
        return ""
    return _("nella cartella {folder}").format(folder=PurePosixPath(folder).name or folder)


def _explain_launched(*, facts: GroupFacts) -> str:
    sentence = _count_processes(count=facts.processes, lead=facts.lead_process)
    folder_phrase = _named_folder(folder=facts.folder)
    if facts.category is Category.DEV_SERVER:
        ports = f" {_ports_phrase(ports=facts.ports)}" if facts.ports else ""
        return _with_folder(sentence=sentence + ports, folder_phrase=folder_phrase)
    launched = ngettext(
        "{sentence} lanciato dal terminale",
        "{sentence} lanciati dal terminale",
        facts.processes,
    ).format(sentence=sentence)
    return _with_ports(
        sentence=_with_folder(sentence=launched, folder_phrase=folder_phrase), ports=facts.ports
    )


def _names_phrase(*, names: tuple[str, ...]) -> str:
    distinct = sorted(set(names))
    shown = ", ".join(distinct[:MAX_LISTED_NAMES])
    hidden = len(distinct) - MAX_LISTED_NAMES
    return _("{shown} e altri {hidden}").format(shown=shown, hidden=hidden) if hidden > 0 else shown


def _explain_other(*, facts: GroupFacts) -> str:
    if facts.tool_reason is not None:
        return f"{_count_processes(count=facts.processes, lead=None)}: {facts.tool_reason}"
    processes = _count_processes(count=facts.processes, lead=facts.lead_process)
    return ngettext(
        "{processes} non riconducibile a un progetto o a un'app",
        "{processes} non riconducibili a un progetto o a un'app",
        facts.processes,
    ).format(processes=processes)


def explain_group(*, facts: GroupFacts) -> str:
    """Describe in the active language why a group exists and what is in it (RF-08).

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
        return _(APP_TEMPLATES[category]).format(name=facts.name, processes=processes)
    if category in PROTECTED_CATEGORIES:
        names = _names_phrase(names=facts.process_names)
        return _("{name}: {names}, {note}").format(
            name=facts.name, names=names, note=_(NOT_MODIFIABLE)
        )
    return _explain_other(facts=facts)
