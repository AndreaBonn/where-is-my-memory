import math
import unicodedata
from datetime import datetime
from types import MappingProxyType

from wimm.core.sizes import format_size as format_size
from wimm.core.text import OBSERVING_PREFIX
from wimm.i18n import N_, _, ngettext
from wimm.model.enums import ActionKind, ActivityState, Category, Pressure, Risk

SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400
ROUND_FROM_BYTES = 10_000_000_000
BYTES_PER_GB = 1_000_000_000

CATEGORY_LABELS = MappingProxyType(
    {
        Category.SYSTEM: N_("Sistema"),
        Category.CONTAINER: N_("Contenitore Docker"),
        Category.DEV_SERVER: N_("Server di sviluppo"),
        Category.DEV_PROCESS: N_("Strumento di sviluppo"),
        Category.AI_CLI: N_("Assistente AI"),
        Category.BROWSER: N_("Browser"),
        Category.DESKTOP_APP: N_("App"),
        Category.TERMINAL: N_("Terminale"),
        Category.SESSION: N_("Sessione"),
        Category.SELF: N_("Monitor"),
        Category.OTHER: N_("Altro"),
        Category.PROJECT: N_("Progetto"),
    }
)
RISK_TEXT = MappingProxyType(
    {Risk.SAFE: N_("Sicuro"), Risk.CAUTION: N_("Attenzione"), Risk.DANGER: N_("Pericolo")}
)
# The badge says the risk and what closing costs (P8); RISK_TEXT stays the short filter label.
RISK_CONSEQUENCE = MappingProxyType(
    {
        Risk.SAFE: N_("Sicuro: non perdi nulla"),
        Risk.CAUTION: N_("Attenzione: puoi perdere lavoro"),
        Risk.DANGER: N_("Pericolo: cancella dati"),
    }
)
# On the disk the cost depends on the item: "caution" sends the user to the confirmation,
# which lists what is lost (a stopped container loses its own files for good).
DISK_RISK_CONSEQUENCE = MappingProxyType(
    {
        Risk.SAFE: N_("Sicuro: si ricrea quando serve"),
        Risk.CAUTION: N_("Attenzione: leggi prima cosa si perde"),
        Risk.DANGER: N_("Pericolo: cancella dati"),
    }
)
# libadwaita style classes (spec 10.4).
RISK_STYLE = MappingProxyType({Risk.SAFE: "success", Risk.CAUTION: "warning", Risk.DANGER: "error"})
# P1/P2: what a non-expert should know about the pressure, none when it is normal.
PRESSURE_PLAIN = MappingProxyType(
    {
        Pressure.OK: "",
        Pressure.WARNING: N_("memoria quasi piena"),
        Pressure.CRITICAL: N_("memoria quasi finita"),
    }
)
PRESSURE_TEXT = MappingProxyType(
    {Pressure.OK: N_("Normale"), Pressure.WARNING: N_("Alta"), Pressure.CRITICAL: N_("Critica")}
)
ACTION_LABELS = MappingProxyType(
    {
        ActionKind.PROCESS_TERMINATE: N_("Termina"),
        ActionKind.PROCESS_KILL: N_("Forza chiusura"),
        ActionKind.APP_CLOSE: N_("Chiudi"),
        ActionKind.CONTAINER_STOP: N_("Ferma"),
        ActionKind.CONTAINER_REMOVE: N_("Rimuovi"),
        ActionKind.GROUP_STOP: N_("Ferma"),
        ActionKind.COMPOSE_DOWN: N_("Spegni il progetto"),
        ActionKind.COMPOSE_DOWN_VOLUMES: N_("Spegni e rimuovi i volumi"),
        ActionKind.STOP_ALL_IDLE_SAFE: N_("Libera la memoria"),
        ActionKind.IMAGE_REMOVE: N_("Rimuovi immagine"),
        ActionKind.IMAGES_PRUNE_DANGLING: N_("Elimina immagini senza nome"),
        ActionKind.IMAGES_PRUNE_UNUSED: N_("Elimina immagini inutilizzate"),
        ActionKind.BUILDER_PRUNE: N_("Svuota cache di build"),
        ActionKind.CONTAINERS_PRUNE_STOPPED: N_("Elimina container fermi"),
        ActionKind.VOLUME_REMOVE: N_("Rimuovi volume"),
        ActionKind.CACHE_CLEAN: N_("Pulisci cache"),
        ActionKind.TRASH_EMPTY: N_("Svuota cestino"),
        ActionKind.DEVDIR_DELETE: N_("Elimina cartella"),
        ActionKind.DISK_FREE_SAFE: N_("Libera spazio"),
        ActionKind.CONTAINER_START: N_("Riaccendi"),
        ActionKind.RESTART_STOPPED: N_("Riaccendi"),
    }
)


def format_elapsed(*, seconds: float) -> str:
    """Format a duration as a relative span such as ``da 5 h`` (floored)."""
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError(f"seconds must be finite and non-negative, got {seconds!r}")
    whole = int(seconds)
    if whole < SECONDS_PER_MINUTE:
        return _("da {count} s").format(count=whole)
    if whole < SECONDS_PER_HOUR:
        return _("da {count} min").format(count=whole // SECONDS_PER_MINUTE)
    if whole < SECONDS_PER_DAY:
        return _("da {count} h").format(count=whole // SECONDS_PER_HOUR)
    days = whole // SECONDS_PER_DAY
    return ngettext("da {count} giorno", "da {count} giorni", days).format(count=days)


def allocate_percents(*, sizes: tuple[int, ...]) -> tuple[int, ...]:
    """Split 100 points across ``sizes`` by largest remainder, so the result sums to 100.

    All zeros (or no sizes) give all zeros. Ties go to the earlier entry.
    """
    total = sum(sizes)
    if total <= 0:
        return tuple(0 for _size in sizes)
    points = [size * 100 // total for size in sizes]
    remainders = [size * 100 % total for size in sizes]
    ranked = sorted(range(len(sizes)), key=lambda i: (-remainders[i], i))
    for index in ranked[: 100 - sum(points)]:
        points[index] += 1
    return tuple(points)


def fold_text(*, text: str) -> str:
    """Casefold and strip accents, for accent-insensitive search."""
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn").casefold()


def format_clock(*, value: datetime, now: datetime) -> str:
    """Format a time in the system time zone: ``HH:MM`` on today's date, else ``DD/MM HH:MM``.

    The service clock is UTC, so the zone of ``now`` says nothing about the user's.
    """
    local = value.astimezone()
    pattern = "%H:%M" if local.date() == now.astimezone().date() else "%d/%m %H:%M"
    return local.strftime(pattern)


def activity_text(*, state: ActivityState, reason: str, elapsed_s: float | None) -> str:
    """Describe an activity state in plain Italian, with the duration for idle ones."""
    if state is ActivityState.ACTIVE:
        return _("in uso")
    if state is ActivityState.IDLE:
        return _("non in uso {elapsed}").format(elapsed=format_elapsed(seconds=elapsed_s or 0))
    return (
        _(OBSERVING_PREFIX)
        if reason.startswith(_(OBSERVING_PREFIX))
        else _("attività non misurabile")
    )


def button_label(*, kind: ActionKind) -> str:
    """Return the button label, the same for every risk: every action asks first (D7)."""
    return _(ACTION_LABELS[kind])


def format_round_size(*, size: int) -> str:
    """Like format_size, but whole gigabytes from 10 GB on (``33 GB``), for headline totals."""
    if size < ROUND_FROM_BYTES:
        return format_size(size=size)
    return f"{(2 * size + BYTES_PER_GB) // (2 * BYTES_PER_GB)} GB"
