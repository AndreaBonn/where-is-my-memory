"""Pure model of the preferences dialog: fields, units and change detection (RF-50, spec 11)."""

from collections.abc import Mapping
from dataclasses import dataclass

from wimm.config import FLOAT_FIELDS, RANGES
from wimm.model.enums import Category, Protection, protection_of

SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
BYTES_PER_MIB = 1024 * 1024
# The spec leaves notify_min_bytes unbounded; the spin row needs a finite top (1 TiB).
MAX_MIN_BYTES_MIB = 1024 * 1024
LIST_SEPARATOR = ","
LIST_KEYS = ("devdirs_roots", "extra_protected_names")
CATEGORIES_KEY = "notify_categories"
BOOLEAN_KEYS = ("foreground_tracking",)


@dataclass(frozen=True)
class NumberField:
    """A numeric preference shown in a friendlier unit than the stored one."""

    key: str
    title: str
    subtitle: str
    factor: int = 1
    digits: int = 0
    step: float = 1

    @property
    def lower(self) -> float:
        return RANGES[self.key][0] / self.factor

    @property
    def upper(self) -> float:
        upper = RANGES[self.key][1]
        return MAX_MIN_BYTES_MIB if upper is None else upper / self.factor


@dataclass(frozen=True)
class FieldGroup:
    """A titled block of the dialog and the configuration keys it shows."""

    title: str
    description: str
    keys: tuple[str, ...]


_NUMBERS = (
    NumberField(
        "sample_interval_s",
        "Intervallo di campionamento (secondi)",
        "Ogni quanto si legge la memoria",
    ),
    NumberField(
        "activity_window_s",
        "Finestra di osservazione (minuti)",
        "Per quanto tempo si misura l'attività",
        factor=SECONDS_PER_MINUTE,
    ),
    NumberField(
        "cpu_active_threshold_pct",
        "Soglia CPU di attività (%)",
        "Sotto questo uso medio un gruppo è inattivo",
        digits=1,
        step=0.1,
    ),
    NumberField(
        "net_active_threshold_bps",
        "Soglia di rete di attività (byte/s)",
        "Sotto questo traffico un gruppo è inattivo",
        step=100,
    ),
    NumberField(
        "notify_after_s",
        "Notifica dopo (minuti)",
        "Quanto deve restare inattivo un gruppo prima della notifica",
        factor=SECONDS_PER_MINUTE,
    ),
    NumberField(
        "notify_min_bytes",
        "Recuperabile minimo (MB)",
        "Sotto questa quantità non si notifica",
        factor=BYTES_PER_MIB,
        step=50,
    ),
    NumberField(
        "max_notifications_per_hour",
        "Notifiche all'ora (massimo)",
        "Oltre questo numero le notifiche aspettano",
    ),
    NumberField(
        "pressure_warning_pct",
        "Pressione: avviso (% libera)",
        "Sotto questa memoria libera la pressione è di avviso",
    ),
    NumberField(
        "pressure_critical_pct",
        "Pressione: critica (% libera)",
        "Deve essere minore della soglia di avviso",
    ),
    NumberField(
        "terminate_timeout_s",
        "Attesa alla chiusura (secondi)",
        "Dopo questo tempo si propone la chiusura forzata",
    ),
    NumberField(
        "devdirs_min_age_days",
        "Età minima delle cartelle (giorni)",
        "Più recenti di così non si propongono",
    ),
    NumberField(
        "devdirs_max_depth", "Profondità massima", "Livelli di sottocartelle da scansionare"
    ),
    NumberField(
        "disk_scan_interval_s",
        "Scansione del disco ogni (ore)",
        "Ogni quanto si ricalcolano le dimensioni",
        factor=SECONDS_PER_HOUR,
    ),
)
NUMBER_FIELDS: Mapping[str, NumberField] = {field.key: field for field in _NUMBERS}

GROUPS = (
    FieldGroup(
        "Campionamento",
        "Come si legge il sistema e quando un gruppo conta come inattivo.",
        (
            "sample_interval_s",
            "activity_window_s",
            "cpu_active_threshold_pct",
            "net_active_threshold_bps",
            "foreground_tracking",
        ),
    ),
    FieldGroup(
        "Notifiche",
        "Quando e per quali categorie arriva una notifica.",
        ("notify_after_s", "notify_min_bytes", "max_notifications_per_hour", CATEGORIES_KEY),
    ),
    FieldGroup(
        "Pressione di memoria",
        "Le soglie in percentuale di memoria libera.",
        ("pressure_warning_pct", "pressure_critical_pct"),
    ),
    FieldGroup(
        "Chiusura",
        "Come si chiudono i processi e quali nomi non si toccano mai.",
        ("terminate_timeout_s", "extra_protected_names"),
    ),
    FieldGroup(
        "Cartelle",
        "Dove cercare node_modules e .venv e ogni quanto.",
        ("devdirs_roots", "devdirs_min_age_days", "devdirs_max_depth", "disk_scan_interval_s"),
    ),
)


def display_value(*, field: NumberField, raw: object) -> float:
    """The stored value as the dialog shows it, rounded like the spin row."""
    if not isinstance(raw, int | float):
        raise TypeError(f"{field.key}: expected a number")
    return round(raw / field.factor, field.digits)


def raw_value(*, field: NumberField, shown: float) -> int | float:
    """The stored value for a number typed in the dialog's unit."""
    value = shown * field.factor
    return round(value, field.digits) if field.key in FLOAT_FIELDS else round(value)


def parse_list(*, text: str) -> list[str]:
    """Split comma separated text into trimmed, non-empty items."""
    return [item.strip() for item in text.split(LIST_SEPARATOR) if item.strip()]


def format_list(*, items: object) -> str:
    """Join stored items for a text entry."""
    if not isinstance(items, list | tuple):
        raise TypeError("expected a list")
    return f"{LIST_SEPARATOR} ".join(str(item) for item in items)


def actionable_categories() -> tuple[Category, ...]:
    """The categories the user can be notified about (those that allow actions)."""
    return tuple(item for item in Category if protection_of(category=item) is Protection.ACTIONABLE)


def _number(*, key: str, shown: object) -> float:
    if isinstance(shown, bool) or not isinstance(shown, int | float):
        raise TypeError(f"{key}: expected a number")
    return shown


def _changed_value(*, key: str, current: object, shown: object) -> tuple[bool, object]:
    if key in NUMBER_FIELDS:
        field = NUMBER_FIELDS[key]
        number = _number(key=key, shown=shown)
        return number != display_value(field=field, raw=current), raw_value(
            field=field, shown=number
        )
    if key in LIST_KEYS:
        text = str(shown)
        # Compare the text, not the parsed items: an entry with a comma or edge spaces
        # would be split by parse_list and look changed although nobody touched it.
        return text != format_list(items=current), parse_list(text=text)
    if key == CATEGORIES_KEY:
        chosen = frozenset(shown) if isinstance(shown, frozenset) else frozenset()
        return chosen != frozenset(current if isinstance(current, list) else ()), sorted(chosen)
    return shown != current, shown


def collect_changes(
    *, current: Mapping[str, object], shown: Mapping[str, object]
) -> dict[str, object]:
    """The stored-form values of the fields whose shown value differs from ``current``.

    A number is compared at the precision shown, so a stored value that is not a multiple
    of its unit (650 s shown as 11 min) is left alone and cannot be set to the round value.
    """
    changes: dict[str, object] = {}
    for key, value in shown.items():
        changed, raw = _changed_value(key=key, current=current[key], shown=value)
        if changed:
            changes[key] = raw
    return changes
