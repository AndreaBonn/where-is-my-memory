from dataclasses import dataclass
from types import MappingProxyType

from wimm.core.text_groups import GroupFacts as GroupFacts
from wimm.core.text_groups import explain_group as explain_group
from wimm.i18n import N_, _, decimal_separator, ngettext
from wimm.model.enums import Category

SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400
MINUTES_UP_TO_S = 2 * SECONDS_PER_HOUR
HOURS_UP_TO_S = 2 * SECONDS_PER_DAY

UNMEASURABLE_LABELS = MappingProxyType(
    {
        Category.BROWSER: N_("i browser"),
        Category.DESKTOP_APP: N_("le app desktop"),
        Category.TERMINAL: N_("i terminali"),
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
    """Format with one decimal and the decimal separator of the active language."""
    return f"{value:.1f}".replace(".", decimal_separator())


def _minutes(*, count: int) -> str:
    return ngettext("{count} minuto", "{count} minuti", count).format(count=count)


def format_duration(*, seconds: float) -> str:
    """Format a duration as ``4 minuti``, ``3 h`` or ``2 giorni`` (floored, never zero)."""
    if seconds < SECONDS_PER_MINUTE:
        return _("meno di 1 minuto")
    if seconds < MINUTES_UP_TO_S:
        return _minutes(count=int(seconds // SECONDS_PER_MINUTE))
    if seconds < HOURS_UP_TO_S:
        return _("{count} h").format(count=int(seconds // SECONDS_PER_HOUR))
    return _days(count=int(seconds // SECONDS_PER_DAY))


def _days(*, count: int) -> str:
    return ngettext("{count} giorno", "{count} giorni", count).format(count=count)


def spoken_duration(*, seconds: float) -> str:
    """Format a duration in whole words, ``40 minuti``, ``1 ora``, ``2 giorni`` (floored)."""
    if seconds < SECONDS_PER_MINUTE:
        return _("meno di 1 minuto")
    if seconds < SECONDS_PER_HOUR:
        return _minutes(count=int(seconds // SECONDS_PER_MINUTE))
    if seconds < SECONDS_PER_DAY:
        hours = int(seconds // SECONDS_PER_HOUR)
        return ngettext("{count} ora", "{count} ore", hours).format(count=hours)
    return _days(count=int(seconds // SECONDS_PER_DAY))


# The UI reads these marks back (translated with ``_``) to tell "observing" and "at least" apart.
OBSERVING_PREFIX = N_("in osservazione")
AT_LEAST_MARK = N_("da almeno")
NO_CONNECTIONS_MARK = N_("nessuna connessione")


def reason_observing(*, elapsed_s: float) -> str:
    return _("{prefix} da {duration}").format(
        prefix=_(OBSERVING_PREFIX), duration=format_duration(seconds=elapsed_s)
    )


def reason_unmeasurable(*, category: Category) -> str:
    label = UNMEASURABLE_LABELS.get(category)
    if label is None:
        return _("attività non misurabile")
    return _("attività non misurabile per {label}").format(label=_(label))


def reason_not_evaluated() -> str:
    return _("attività non valutata per questa categoria")


def reason_cpu_unavailable() -> str:
    return _("CPU non misurabile negli ultimi campioni")


def reason_active(*, active_for_s: float) -> str:
    return _("attività rilevata da {duration}").format(
        duration=format_duration(seconds=active_for_s)
    )


def _connections_phrase(*, has_port: bool) -> str:
    template = _("{mark} nuova") if has_port else _("{mark} in ingresso")
    return template.format(mark=_(NO_CONNECTIONS_MARK))


def _idle_detail(*, facts: IdleFacts) -> str:
    window = format_duration(seconds=facts.window_s)
    cpu = _("CPU media {value}%").format(value=format_decimal(value=facts.cpu_avg_pct))
    if facts.watches_connections:
        connections = _connections_phrase(has_port=bool(facts.open_port))
        detail = _("{connections} e {cpu} negli ultimi {window}").format(
            connections=connections, cpu=cpu, window=window
        )
    elif facts.net_avg_bps is not None:
        net = _("traffico di rete medio {rate} B/s").format(rate=f"{facts.net_avg_bps:.0f}")
        detail = _("{cpu} e {net} negli ultimi {window}").format(cpu=cpu, net=net, window=window)
    else:
        detail = _("{cpu} negli ultimi {window}").format(cpu=cpu, window=window)
    if facts.open_port:
        detail += "; " + _(
            "c'è una connessione aperta da un browser "
            "(probabile scheda dimenticata su localhost:{port})"
        ).format(port=facts.open_port)
    return detail


def _idle_prefix(*, duration: str, from_monitor_start: bool) -> str:
    if from_monitor_start:
        return _("inattivo {at_least} {duration}, cioè da quando il monitor è partito").format(
            at_least=_(AT_LEAST_MARK), duration=duration
        )
    return _("inattivo da {duration}").format(duration=duration)


def reason_idle(*, idle_for_s: float, facts: IdleFacts, from_monitor_start: bool) -> str:
    duration = format_duration(seconds=idle_for_s)
    prefix = _idle_prefix(duration=duration, from_monitor_start=from_monitor_start)
    return f"{prefix}; {_idle_detail(facts=facts)}"


def reason_foreground_idle(*, idle_for_s: float, window_s: float, from_monitor_start: bool) -> str:
    duration = format_duration(seconds=idle_for_s)
    prefix = _idle_prefix(duration=duration, from_monitor_start=from_monitor_start)
    tail = _("mai in primo piano negli ultimi {window}").format(
        window=format_duration(seconds=window_s)
    )
    return f"{prefix}; {tail}"


def reason_foreground_active(*, ago_s: float) -> str:
    return _("in primo piano {duration} fa").format(duration=format_duration(seconds=ago_s))


def reason_idle_persisted(*, idle_for_s: float, observed_s: float) -> str:
    return _(
        "inattivo da {idle}; ultima attività registrata prima del riavvio, {prefix} da {observed}"
    ).format(
        idle=format_duration(seconds=idle_for_s),
        prefix=_(OBSERVING_PREFIX),
        observed=format_duration(seconds=observed_s),
    )


def reason_group_active(*, active: int, measurable: int) -> str:
    if measurable == 1:
        return _("l'unico membro misurabile è attivo")
    return ngettext(
        "{active} membro attivo su {measurable} misurabili",
        "{active} membri attivi su {measurable} misurabili",
        active,
    ).format(active=active, measurable=measurable)


def reason_group_idle(*, measurable: int) -> str:
    if measurable == 1:
        return _("l'unico membro misurabile è inattivo")
    if measurable == 2:
        return _("entrambi i membri misurabili sono inattivi")
    return _("tutti i {measurable} membri misurabili sono inattivi").format(measurable=measurable)


def reason_group_unknown(*, measurable: int) -> str:
    if measurable == 0:
        return _("nessun membro misurabile")
    if measurable == 1:
        return _("attività dell'unico membro misurabile ancora non determinata")
    return _(
        "attività di almeno uno dei {measurable} membri misurabili ancora non determinata"
    ).format(measurable=measurable)
