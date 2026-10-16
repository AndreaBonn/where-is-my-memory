from dataclasses import dataclass
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
