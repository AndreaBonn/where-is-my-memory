"""Active user-interface language and the gettext functions bound to it.

The source strings are Italian, so Italian needs no catalog: it is the identity. Every
other language reads ``locale/<lang>/LC_MESSAGES/wimm.mo`` next to this module. The
language can change while the app runs, so callers translate at use time: module-level
constants are only marked with :func:`N_` and passed to :func:`_` where they are shown.
"""

import gettext
import logging
from collections.abc import Mapping
from pathlib import Path

LOGGER = logging.getLogger(__name__)
DOMAIN = "wimm"
ITALIAN = "it"
ENGLISH = "en"
LANGUAGES = (ITALIAN, ENGLISH)
LOCALE_DIR = Path(__file__).resolve().parent / "locale"
# Same precedence gettext.find() uses: the first non-empty variable wins.
LOCALE_VARIABLES = ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG")
DECIMAL_SEPARATORS = {ITALIAN: ",", ENGLISH: "."}

# A single reference swapped in one assignment: the sampler thread never sees half a change.
_state: tuple[str, gettext.NullTranslations] = (ITALIAN, gettext.NullTranslations())


def resolve_default(*, environ: Mapping[str, str]) -> str:
    """Return the language to use when the user has not chosen one.

    An English system locale gives English; every other locale, ``C`` included, keeps
    Italian, the language the app was written in.
    """
    value = next((environ[name] for name in LOCALE_VARIABLES if environ.get(name)), "")
    # Like gettext.find(), every entry of ``LANGUAGE=de:en`` is tried in order.
    for entry in value.lower().split(":"):
        if entry.startswith(LANGUAGES):
            return entry[: len(ENGLISH)]
    return ITALIAN


def set_language(*, language: str, locale_dir: Path = LOCALE_DIR) -> None:
    """Make ``language`` the one every later translation call returns.

    A missing catalog is logged and leaves the Italian source text visible.

    Raises
    ------
    ValueError
        If ``language`` is not one of :data:`LANGUAGES`.
    """
    global _state
    if language not in LANGUAGES:
        raise ValueError(f"Unsupported language: {language}")
    if language == ITALIAN:
        _state = (language, gettext.NullTranslations())
        return
    try:
        translations = gettext.translation(
            DOMAIN, localedir=locale_dir, languages=[language], fallback=True
        )
    except (OSError, UnicodeError) as error:
        LOGGER.warning("Unreadable %s catalog in %s: %s", language, locale_dir, error)
        translations = gettext.NullTranslations()
    if not isinstance(translations, gettext.GNUTranslations):
        LOGGER.warning("No %s catalog in %s, showing Italian text", language, locale_dir)
    _state = (language, translations)


def current_language() -> str:
    """Return the active language code."""
    return _state[0]


def decimal_separator() -> str:
    """Return the decimal separator of the active language."""
    return DECIMAL_SEPARATORS[_state[0]]


def _(message: str) -> str:
    """Translate ``message`` into the active language."""
    return _state[1].gettext(message)


def ngettext(singular: str, plural: str, count: int) -> str:
    """Translate and pick the plural form for ``count``."""
    return _state[1].ngettext(singular, plural, count)


def pgettext(context: str, message: str) -> str:
    """Translate ``message`` where the same Italian text has more than one meaning."""
    return _state[1].pgettext(context, message)


def N_(message: str) -> str:
    """Mark ``message`` for extraction without translating it yet."""
    return message
