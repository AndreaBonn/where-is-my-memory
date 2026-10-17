import json
import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

from wimm.config_messages import field_message, pressure_order_message, range_message
from wimm.config_roots import decode_roots, default_roots, validate_roots
from wimm.core import constants as c
from wimm.i18n import LANGUAGES
from wimm.model import Category, Protection, protection_of
from wimm.paths import UserPaths, ensure_private_dir, write_private_atomic

LOGGER = logging.getLogger(__name__)
CONFIG_FILE = "config.json"
RANGES: Mapping[str, tuple[int | float, int | float | None]] = MappingProxyType(
    {
        "sample_interval_s": (10, 300),
        "activity_window_s": (300, 14400),
        "cpu_active_threshold_pct": (0.1, 50),
        "net_active_threshold_bps": (0, 10485760),
        "notify_after_s": (600, 604800),
        "notify_min_bytes": (0, None),
        "pressure_warning_pct": (5, 50),
        "pressure_critical_pct": (1, 50),
        "max_notifications_per_hour": (1, 20),
        "terminate_timeout_s": (1, 60),
        "devdirs_min_age_days": (7, 3650),
        "devdirs_max_depth": (1, 12),
        "disk_scan_interval_s": (3600, 604800),
    }
)
FLOAT_FIELDS = frozenset({"cpu_active_threshold_pct"})
_PRESSURE_FIELDS = frozenset({"pressure_warning_pct", "pressure_critical_pct"})


@dataclass(frozen=True)
class Config:
    """Validated application preferences; paths are stored as absolute paths."""

    sample_interval_s: int = c.SAMPLE_INTERVAL_S
    activity_window_s: int = c.ACTIVITY_WINDOW_S
    cpu_active_threshold_pct: float = c.CPU_ACTIVE_THRESHOLD_PCT
    net_active_threshold_bps: int = c.NET_ACTIVE_THRESHOLD_BPS
    notify_after_s: int = c.NOTIFY_AFTER_S
    notify_min_bytes: int = c.NOTIFY_MIN_BYTES
    notify_categories: frozenset[Category] = frozenset(Category(v) for v in c.NOTIFY_CATEGORIES)
    pressure_warning_pct: int = c.PRESSURE_WARNING_PCT
    pressure_critical_pct: int = c.PRESSURE_CRITICAL_PCT
    max_notifications_per_hour: int = c.MAX_NOTIFICATIONS_PER_HOUR
    terminate_timeout_s: int = c.TERMINATE_TIMEOUT_S
    devdirs_roots: tuple[Path, ...] = field(default_factory=lambda: default_roots(home=Path.home()))
    devdirs_min_age_days: int = c.DEVDIRS_MIN_AGE_DAYS
    devdirs_max_depth: int = c.DEVDIRS_MAX_DEPTH
    disk_scan_interval_s: int = c.DISK_SCAN_INTERVAL_S
    extra_protected_names: tuple[str, ...] = c.EXTRA_PROTECTED_NAMES
    foreground_tracking: bool = c.FOREGROUND_TRACKING
    # None follows the system locale (wimm.i18n.resolve_default).
    language: str | None = None

    def __post_init__(self) -> None:
        for name in RANGES:
            _validate_number(name=name, value=getattr(self, name))
        _validate_collections(config=self)
        if type(self.foreground_tracking) is not bool:
            raise ValueError("foreground_tracking must be a boolean")
        if self.language is not None and self.language not in LANGUAGES:
            raise ValueError("language must be a supported language code")
        if self.pressure_critical_pct >= self.pressure_warning_pct:
            raise ValueError("pressure_critical_pct must be below pressure_warning_pct")

    @property
    def protected_names(self) -> frozenset[str]:
        """Return built-in protection patterns together with user additions."""
        return frozenset((*c.PROTECTED_PROCESS_NAMES, *self.extra_protected_names))


@dataclass(frozen=True)
class ConfigParseResult:
    """Preferences and per-field Italian validation messages for the UI."""

    config: Config
    field_errors: Mapping[str, str]


def _validate_number(name: str, value: object) -> None:
    lower, upper = RANGES[name]
    types = (int, float) if name in FLOAT_FIELDS else (int,)
    if not isinstance(value, int | float) or type(value) not in types:
        raise ValueError(f"{name}: invalid numeric type")
    if (isinstance(value, float) and not math.isfinite(value)) or value < lower:
        raise ValueError(f"{name}: below range or non-finite")
    if upper is not None and value > upper:
        raise ValueError(f"{name}: above range")


def _validate_collections(config: Config) -> None:
    categories = config.notify_categories
    if not isinstance(categories, frozenset) or any(
        not isinstance(item, Category) or protection_of(category=item) is not Protection.ACTIONABLE
        for item in categories
    ):
        raise ValueError("notify_categories must contain actionable categories")
    if type(config.extra_protected_names) is not tuple or any(
        type(item) is not str or not item for item in config.extra_protected_names
    ):
        raise ValueError("extra_protected_names must be a tuple of strings")
    validate_roots(roots=config.devdirs_roots)


def _decode_field(name: str, value: object, home: Path) -> Any:
    if name in RANGES:
        _validate_number(name=name, value=value)
        return value
    if name == "foreground_tracking":
        if type(value) is not bool:
            raise ValueError("Expected boolean")
        return value
    if name == "language":
        if value is not None and value not in LANGUAGES:
            raise ValueError("Expected a supported language code")
        return value
    if not isinstance(value, list) or any(type(item) is not str for item in value):
        raise ValueError("Expected a list of strings")
    if name == "notify_categories":
        categories = frozenset(Category(item) for item in value)
        if any(protection_of(category=item) is not Protection.ACTIONABLE for item in categories):
            raise ValueError("Expected actionable categories")
        return categories
    if name == "extra_protected_names":
        if any(not item for item in value):
            raise ValueError("Expected nonempty process names")
        return tuple(value)
    return decode_roots(value=value, home=home)


def _field_error(name: str) -> str:
    if name in RANGES:
        lower, upper = RANGES[name]
        return range_message(name=name, lower=lower, upper=upper, integer=name not in FLOAT_FIELDS)
    return field_message(name=name)


def parse_config(raw: Mapping[str, object], home: Path) -> ConfigParseResult:
    """Validate raw preferences, keeping defaults for invalid fields.

    Parameters
    ----------
    raw : Mapping[str, object]
        JSON preferences; unknown keys are logged and discarded.
    home : Path
        Home used for tilde expansion and directory containment.

    Returns
    -------
    ConfigParseResult
        Validated preferences and messages keyed by invalid field.
    """
    values: dict[str, Any] = {"devdirs_roots": default_roots(home=home)}
    errors: dict[str, str] = {}
    names = {item.name for item in fields(Config)}
    for name, value in raw.items():
        if name not in names:
            LOGGER.warning("Unknown configuration key: %s", name)
            continue
        try:
            values[name] = _decode_field(name=name, value=value, home=home)
        except (ValueError, OSError):
            errors[name] = _field_error(name=name)
    _restore_pressure_defaults(values=values, errors=errors)
    return ConfigParseResult(config=Config(**values), field_errors=MappingProxyType(errors))


def _restore_pressure_defaults(values: dict[str, Any], errors: dict[str, str]) -> None:
    warning = values.get("pressure_warning_pct", c.PRESSURE_WARNING_PCT)
    critical = values.get("pressure_critical_pct", c.PRESSURE_CRITICAL_PCT)
    if critical >= warning:
        values.update(
            pressure_warning_pct=c.PRESSURE_WARNING_PCT,
            pressure_critical_pct=c.PRESSURE_CRITICAL_PCT,
        )
        errors["pressure_critical_pct"] = pressure_order_message()


def update_config(config: Config, changes: Mapping[str, object], home: Path) -> ConfigParseResult:
    """Apply ``changes`` to ``config`` without mutating either argument.

    Parameters
    ----------
    config : Config
        Current preferences.
    changes : Mapping[str, object]
        Raw new values; unknown keys are logged and discarded.
    home : Path
        Home used for tilde expansion and directory containment.

    Returns
    -------
    ConfigParseResult
        New preferences where every invalid field keeps its previous value, and
        messages for the invalid fields the caller tried to change.
    """
    parsed = parse_config(raw={**config_to_raw(config=config), **changes}, home=home)
    invalid = set(parsed.field_errors)
    if "pressure_critical_pct" in invalid:
        invalid |= _PRESSURE_FIELDS
    restored = replace(parsed.config, **{name: getattr(config, name) for name in invalid})
    touched = {*changes, *(_PRESSURE_FIELDS if _PRESSURE_FIELDS & set(changes) else ())}
    errors = {name: text for name, text in parsed.field_errors.items() if name in touched}
    return ConfigParseResult(config=restored, field_errors=MappingProxyType(errors))


def config_to_raw(config: Config) -> dict[str, object]:
    """Serialize preferences with absolute directory paths and JSON values.

    Parameters
    ----------
    config : Config
        Validated preferences to serialize.
    """
    raw = {item.name: getattr(config, item.name) for item in fields(config)}
    raw["notify_categories"] = sorted(item.value for item in config.notify_categories)
    raw["devdirs_roots"] = [str(item) for item in config.devdirs_roots]
    raw["extra_protected_names"] = list(config.extra_protected_names)
    return raw


def load_config(paths: UserPaths, home: Path) -> ConfigParseResult:
    """Load preferences; missing or malformed JSON falls back to defaults.

    Parameters
    ----------
    paths : UserPaths
        Explicit configuration directory.
    home : Path
        Home used for tilde expansion and directory containment.
    """
    try:
        raw = json.loads((paths.config_dir / CONFIG_FILE).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Configuration must be a JSON object")
    except FileNotFoundError:
        raw = {}
    except (ValueError, OSError) as error:
        LOGGER.warning("Cannot load configuration: %s", error)
        raw = {}
    return parse_config(raw=raw, home=home)


def save_config(paths: UserPaths, config: Config) -> None:
    """Atomically save private preferences as indented, sorted JSON.

    Parameters
    ----------
    paths : UserPaths
        Explicit configuration directory.
    config : Config
        Validated preferences to persist.
    """
    ensure_private_dir(path=paths.config_dir)
    data = json.dumps(config_to_raw(config=config), indent=2, sort_keys=True).encode("utf-8")
    write_private_atomic(path=paths.config_dir / CONFIG_FILE, data=data)
