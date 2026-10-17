"""Pure model of the preferences dialog: fields, units and change detection (RF-50, spec 11)."""

from collections.abc import Mapping
from dataclasses import dataclass

from wimm.config import FLOAT_FIELDS, RANGES
from wimm.i18n import N_
from wimm.model.enums import Category, Protection, protection_of

SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
BYTES_PER_MIB = 1024 * 1024
BYTES_PER_KB = 1000
# The spec leaves notify_min_bytes unbounded; the spin row needs a finite top (1 TiB).
MAX_MIN_BYTES_MIB = 1024 * 1024
LIST_SEPARATOR = ","
LIST_KEYS = ("devdirs_roots", "extra_protected_names")
CATEGORIES_KEY = "notify_categories"
BOOLEAN_KEYS = ("foreground_tracking",)
# Applied by their own row as soon as they change: never part of "Applica" or of a reset.
IMMEDIATE_KEYS = ("language",)


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


# R2: each title reads as a sentence, the unit in brackets; the subtitle says why it matters.
_NUMBERS = (
    NumberField(
        "sample_interval_s",
        N_("Controlla la memoria ogni (secondi)"),
        N_("Più spesso è più preciso, ma usa un po' più di processore"),
    ),
    NumberField(
        "activity_window_s",
        N_("Per decidere se è in uso, guarda gli ultimi (minuti)"),
        N_("Un programma è in uso se ha lavorato in questo tempo"),
        factor=SECONDS_PER_MINUTE,
    ),
    NumberField(
        "cpu_active_threshold_pct",
        N_("È fermo se usa meno del processore di (%)"),
        N_("Media sul tempo osservato"),
        digits=1,
        step=0.1,
    ),
    NumberField(
        "net_active_threshold_bps",
        N_("È fermo se scambia in rete meno di (kB al secondo)"),
        N_("Media sul tempo osservato"),
        factor=BYTES_PER_KB,
        digits=1,
        step=0.1,
    ),
    NumberField(
        "notify_after_s",
        N_("Avvisami se non lo usi da (minuti)"),
        N_("Prima di questo tempo non arriva nessun avviso"),
        factor=SECONDS_PER_MINUTE,
    ),
    NumberField(
        "notify_min_bytes",
        N_("Avvisami solo se libero almeno (MB)"),
        N_("Per i programmi più piccoli non arriva nessun avviso"),
        factor=BYTES_PER_MIB,
        step=50,
    ),
    NumberField(
        "max_notifications_per_hour",
        N_("Avvisi singoli in un'ora"),
        N_("Gli altri arrivano insieme in uno solo; memoria o disco pieni si segnalano sempre"),
    ),
    NumberField(
        "pressure_warning_pct",
        N_("Quasi pieno quando resta libero meno del (%)"),
        N_("Vale per la memoria e per il disco: da qui compare l'avviso"),
    ),
    NumberField(
        "pressure_critical_pct",
        N_("Pieno quando resta libero meno del (%)"),
        N_("Deve essere minore della soglia precedente"),
    ),
    NumberField(
        "terminate_timeout_s",
        N_("Se non si chiude, proponi la chiusura forzata dopo (secondi)"),
        N_("Il tempo che un programma ha per chiudersi da solo"),
    ),
    NumberField(
        "devdirs_min_age_days",
        N_("Proponi le cartelle non usate da almeno (giorni)"),
        N_("Le cartelle node_modules e .venv più recenti restano fuori"),
    ),
    NumberField(
        "devdirs_max_depth",
        N_("Cerca fino a questi livelli di sottocartelle"),
        N_("Più livelli trovano di più, ma la ricerca dura di più"),
    ),
    NumberField(
        "disk_scan_interval_s",
        N_("Ricontrolla il disco ogni (ore)"),
        N_("Il controllo calcola quanto occupano cartelle e cache"),
        factor=SECONDS_PER_HOUR,
    ),
)
NUMBER_FIELDS: Mapping[str, NumberField] = {field.key: field for field in _NUMBERS}

# R1: in view only what a non-expert changes; the rest behind "Impostazioni avanzate".
ESSENTIAL_GROUPS = (
    FieldGroup(
        N_("Avvisi"),
        N_("Quando ti avvisiamo di un programma acceso che non usi."),
        ("notify_after_s", "notify_min_bytes", CATEGORIES_KEY),
    ),
)
ADVANCED_GROUPS = (
    FieldGroup(
        N_("Come si capisce se un programma è in uso"),
        N_("Quanto spesso si controlla e quando un programma conta come fermo."),
        (
            "sample_interval_s",
            "activity_window_s",
            "cpu_active_threshold_pct",
            "net_active_threshold_bps",
            "foreground_tracking",
        ),
    ),
    FieldGroup(
        N_("Quanti avvisi"),
        N_("Il limite di avvisi, oltre a quanto scelto in Avvisi."),
        ("max_notifications_per_hour",),
    ),
    FieldGroup(
        N_("Memoria e disco quasi pieni"),
        N_("Le soglie in percentuale di spazio libero."),
        ("pressure_warning_pct", "pressure_critical_pct"),
    ),
    FieldGroup(
        N_("Chiusura dei programmi"),
        N_("Quanto si aspetta e quali programmi non si toccano mai."),
        ("terminate_timeout_s", "extra_protected_names"),
    ),
    FieldGroup(
        N_("Cartelle di sviluppo"),
        N_("Dove cercare node_modules e .venv e ogni quanto."),
        ("devdirs_roots", "devdirs_min_age_days", "devdirs_max_depth", "disk_scan_interval_s"),
    ),
)
GROUPS = ESSENTIAL_GROUPS + ADVANCED_GROUPS


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
