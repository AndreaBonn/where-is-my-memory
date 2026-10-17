"""Per-field messages shown in the preferences when a value is rejected (RF-50)."""

from types import MappingProxyType

from wimm.i18n import N_, _

SECONDS_SUFFIX = "_s"
FIELD_MESSAGES = MappingProxyType(
    {
        "notify_categories": N_("Scegli solo categorie su cui sono consentite azioni"),
        "devdirs_roots": N_("Indica directory esistenti all'interno della home"),
        "extra_protected_names": N_("Indica una lista di nomi di processo"),
        "foreground_tracking": N_("Deve essere un valore booleano"),
        "language": N_("Scegli una lingua disponibile"),
    }
)
PRESSURE_ORDER_MESSAGE = N_("Deve essere minore della soglia di avviso")


def range_message(*, name: str, lower: float, upper: float | None, integer: bool) -> str:
    """The rule a number field breaks, such as "Deve essere un numero intero fra 1 e 12"."""
    number = _("un numero intero") if integer else _("un numero")
    unit = _(" secondi") if name.endswith(SECONDS_SUFFIX) else ""
    if upper is None:
        return _("Deve essere {number} almeno {lower}{unit}").format(
            number=number, lower=lower, unit=unit
        )
    return _("Deve essere {number} fra {lower} e {upper}{unit}").format(
        number=number, lower=lower, upper=upper, unit=unit
    )


def field_message(*, name: str) -> str:
    """The message of a non-numeric field, in the active language."""
    return _(FIELD_MESSAGES[name])


def pressure_order_message() -> str:
    """The message shown when the critical threshold is not below the warning one."""
    return _(PRESSURE_ORDER_MESSAGE)
