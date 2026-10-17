import math
import unicodedata
from datetime import datetime
from types import MappingProxyType

from wimm.core.sizes import format_size as format_size
from wimm.model.enums import ActionKind, ActivityState, Category, Pressure, Risk

SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400
OBSERVING_PREFIX = "in osservazione"
ELLIPSIS = "…"

CATEGORY_LABELS = MappingProxyType(
    {
        Category.SYSTEM: "Sistema",
        Category.CONTAINER: "Container",
        Category.DEV_SERVER: "Dev server",
        Category.DEV_PROCESS: "Processo di sviluppo",
        Category.AI_CLI: "CLI AI",
        Category.BROWSER: "Browser",
        Category.DESKTOP_APP: "App",
        Category.TERMINAL: "Terminale",
        Category.SESSION: "Sessione",
        Category.SELF: "Monitor",
        Category.OTHER: "Altro",
        Category.PROJECT: "Progetto",
    }
)
RISK_TEXT = MappingProxyType(
    {Risk.SAFE: "Sicuro", Risk.CAUTION: "Attenzione", Risk.DANGER: "Pericolo"}
)
# libadwaita style classes (spec 10.4).
RISK_STYLE = MappingProxyType({Risk.SAFE: "success", Risk.CAUTION: "warning", Risk.DANGER: "error"})
PRESSURE_TEXT = MappingProxyType(
    {Pressure.OK: "Normale", Pressure.WARNING: "Alta", Pressure.CRITICAL: "Critica"}
)
ACTION_LABELS = MappingProxyType(
    {
        ActionKind.PROCESS_TERMINATE: "Termina",
        ActionKind.PROCESS_KILL: "Forza chiusura",
        ActionKind.APP_CLOSE: "Chiudi",
        ActionKind.CONTAINER_STOP: "Ferma",
        ActionKind.CONTAINER_REMOVE: "Rimuovi",
        ActionKind.GROUP_STOP: "Ferma",
        ActionKind.COMPOSE_DOWN: "Spegni il progetto",
        ActionKind.COMPOSE_DOWN_VOLUMES: "Spegni e rimuovi i volumi",
        ActionKind.STOP_ALL_IDLE_SAFE: "Ferma tutti gli inattivi sicuri",
        ActionKind.IMAGE_REMOVE: "Rimuovi immagine",
        ActionKind.IMAGES_PRUNE_DANGLING: "Elimina immagini senza nome",
        ActionKind.IMAGES_PRUNE_UNUSED: "Elimina immagini inutilizzate",
        ActionKind.BUILDER_PRUNE: "Svuota cache di build",
        ActionKind.CONTAINERS_PRUNE_STOPPED: "Elimina container fermi",
        ActionKind.VOLUME_REMOVE: "Rimuovi volume",
        ActionKind.CACHE_CLEAN: "Pulisci cache",
        ActionKind.TRASH_EMPTY: "Svuota cestino",
        ActionKind.DEVDIR_DELETE: "Elimina cartella",
    }
)


def format_elapsed(*, seconds: float) -> str:
    """Format a duration as a relative span such as ``da 5 h`` (floored)."""
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError(f"seconds must be finite and non-negative, got {seconds!r}")
    whole = int(seconds)
    if whole < SECONDS_PER_MINUTE:
        return f"da {whole} s"
    if whole < SECONDS_PER_HOUR:
        return f"da {whole // SECONDS_PER_MINUTE} min"
    if whole < SECONDS_PER_DAY:
        return f"da {whole // SECONDS_PER_HOUR} h"
    days = whole // SECONDS_PER_DAY
    return f"da {days} {'giorno' if days == 1 else 'giorni'}"


def allocate_percents(*, sizes: tuple[int, ...]) -> tuple[int, ...]:
    """Split 100 points across ``sizes`` by largest remainder, so the result sums to 100.

    All zeros (or no sizes) give all zeros. Ties go to the earlier entry.
    """
    total = sum(sizes)
    if total <= 0:
        return tuple(0 for _ in sizes)
    points = [size * 100 // total for size in sizes]
    remainders = [size * 100 % total for size in sizes]
    ranked = sorted(range(len(sizes)), key=lambda i: (-remainders[i], i))
    for index in ranked[: 100 - sum(points)]:
        points[index] += 1
    return tuple(points)


def percent_text(*, percent: int, size: int) -> str:
    """Render a percent; a non-empty share rounded to zero reads ``<1%``."""
    return "<1%" if percent == 0 and size > 0 else f"{percent}%"


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
        return "in uso"
    if state is ActivityState.IDLE:
        return f"inattivo {format_elapsed(seconds=elapsed_s or 0)}"
    return OBSERVING_PREFIX if reason.startswith(OBSERVING_PREFIX) else "attività non misurabile"


def button_label(*, kind: ActionKind, risk: Risk) -> str:
    """Return the button label; caution and danger end with an ellipsis (confirmation)."""
    label = ACTION_LABELS[kind]
    return label if risk is Risk.SAFE else label + ELLIPSIS
