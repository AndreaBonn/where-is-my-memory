"""R3/R4: alert presets and the recommended values of the preferences. Pure, no GTK."""

from collections.abc import Mapping
from dataclasses import dataclass

from wimm.config import Config, config_to_raw
from wimm.core.text import spoken_duration
from wimm.i18n import N_, _, ngettext
from wimm.ui.dialogs.preferences_model import BYTES_PER_MIB, IMMEDIATE_KEYS, LIST_KEYS

AFTER_KEY = "notify_after_s"
MIN_BYTES_KEY = "notify_min_bytes"
PER_HOUR_KEY = "max_notifications_per_hour"
PRESET_KEYS = (AFTER_KEY, MIN_BYTES_KEY, PER_HOUR_KEY)
SECONDS_PER_HOUR = 3600
CUSTOM_SENTENCE = N_(
    "Personalizzati: valgono i valori scelti qui sotto e nelle impostazioni avanzate."
)
_DEFAULTS = Config()


@dataclass(frozen=True, slots=True, kw_only=True)
class Preset:
    """A named level of alerts and the three values it sets.

    ``name`` is the Italian msgid: it is also the key of the toggles, so it is translated
    only where it is shown.
    """

    name: str
    values: Mapping[str, int]


PRESETS = (
    Preset(
        name=N_("Pochi"),
        values={
            AFTER_KEY: 4 * SECONDS_PER_HOUR,
            MIN_BYTES_KEY: 500 * BYTES_PER_MIB,
            PER_HOUR_KEY: 1,
        },
    ),
    Preset(
        name=N_("Normali"),
        values={
            AFTER_KEY: _DEFAULTS.notify_after_s,
            MIN_BYTES_KEY: _DEFAULTS.notify_min_bytes,
            PER_HOUR_KEY: _DEFAULTS.max_notifications_per_hour,
        },
    ),
    Preset(
        name=N_("Tanti"),
        values={AFTER_KEY: SECONDS_PER_HOUR, MIN_BYTES_KEY: 100 * BYTES_PER_MIB, PER_HOUR_KEY: 6},
    ),
)


def matching_preset(*, values: Mapping[str, object]) -> Preset | None:
    """The preset whose three values are the ones given, None when set by hand."""
    return next((p for p in PRESETS if all(values.get(k) == v for k, v in p.values.items())), None)


def preset_sentence(*, preset: Preset | None) -> str:
    """What a preset means, in words: "Normali: ti avvisiamo se ... per 2 ore ..."."""
    if preset is None:
        return _(CUSTOM_SENTENCE)
    times = preset.values[PER_HOUR_KEY]
    template = ngettext(
        "{name}: ti avvisiamo se qualcosa resta acceso senza uso per {duration} e libera "
        "almeno {size} MB, fino a {times} avviso all'ora (gli altri insieme in uno solo).",
        "{name}: ti avvisiamo se qualcosa resta acceso senza uso per {duration} e libera "
        "almeno {size} MB, fino a {times} avvisi all'ora (gli altri insieme in uno solo).",
        times,
    )
    return template.format(
        name=_(preset.name),
        duration=spoken_duration(seconds=preset.values[AFTER_KEY]),
        size=preset.values[MIN_BYTES_KEY] // BYTES_PER_MIB,
        times=times,
    )


def recommended_values() -> dict[str, object]:
    """R4: the factory values of every setting except the user's names and folders."""
    kept = {*LIST_KEYS, *IMMEDIATE_KEYS}
    return {k: v for k, v in config_to_raw(config=Config()).items() if k not in kept}
