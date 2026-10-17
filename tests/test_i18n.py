import shutil
import subprocess
from pathlib import Path

import pytest

from wimm import i18n

MSGFMT = shutil.which("msgfmt")
CATALOG = """msgid ""
msgstr ""
"Content-Type: text/plain; charset=UTF-8\\n"
"Plural-Forms: nplurals=2; plural=(n != 1);\\n"

msgid "Applica"
msgstr "Apply"

msgid "{n} giorno"
msgid_plural "{n} giorni"
msgstr[0] "{n} day"
msgstr[1] "{n} days"

msgctxt "tray.menu"
msgid "Esci"
msgstr "Quit"
"""


@pytest.fixture
def locale_dir(tmp_path: Path) -> Path:
    if MSGFMT is None:
        pytest.skip("msgfmt not installed")
    target = tmp_path / "locale" / "en" / "LC_MESSAGES"
    target.mkdir(parents=True)
    source = tmp_path / "en.po"
    source.write_text(CATALOG, encoding="utf-8")
    subprocess.run(  # noqa: S603
        [MSGFMT, "--check", "-o", str(target / f"{i18n.DOMAIN}.mo"), str(source)], check=True
    )
    return tmp_path / "locale"


def test_gettext_italian_returns_source_text() -> None:
    i18n.set_language(language=i18n.ITALIAN)
    assert i18n._("Applica") == "Applica"
    assert i18n.ngettext("{n} giorno", "{n} giorni", 1) == "{n} giorno"
    assert i18n.ngettext("{n} giorno", "{n} giorni", 3) == "{n} giorni"


def test_gettext_english_reads_compiled_catalog(locale_dir: Path) -> None:
    i18n.set_language(language=i18n.ENGLISH, locale_dir=locale_dir)
    assert i18n.current_language() == i18n.ENGLISH
    assert i18n._("Applica") == "Apply"
    assert i18n.ngettext("{n} giorno", "{n} giorni", 1) == "{n} day"
    assert i18n.ngettext("{n} giorno", "{n} giorni", 2) == "{n} days"
    assert i18n.pgettext("tray.menu", "Esci") == "Quit"


def test_gettext_english_missing_entry_falls_back_to_source(locale_dir: Path) -> None:
    i18n.set_language(language=i18n.ENGLISH, locale_dir=locale_dir)
    assert i18n._("Ferma") == "Ferma"
    assert i18n.pgettext("other.context", "Esci") == "Esci"


def test_set_language_missing_catalog_falls_back_to_source(tmp_path: Path) -> None:
    i18n.set_language(language=i18n.ENGLISH, locale_dir=tmp_path)
    assert i18n.current_language() == i18n.ENGLISH
    assert i18n._("Applica") == "Applica"


def test_set_language_corrupt_catalog_falls_back_to_source(tmp_path: Path) -> None:
    target = tmp_path / "en" / "LC_MESSAGES"
    target.mkdir(parents=True)
    (target / f"{i18n.DOMAIN}.mo").write_bytes(b"not a catalog")
    i18n.set_language(language=i18n.ENGLISH, locale_dir=tmp_path)
    assert i18n.current_language() == i18n.ENGLISH
    assert i18n._("Applica") == "Applica"


def test_set_language_back_to_italian_drops_catalog(locale_dir: Path) -> None:
    i18n.set_language(language=i18n.ENGLISH, locale_dir=locale_dir)
    i18n.set_language(language=i18n.ITALIAN)
    assert i18n._("Applica") == "Applica"
    assert i18n.current_language() == i18n.ITALIAN


def test_set_language_unknown_raises() -> None:
    with pytest.raises(ValueError, match="fr"):
        i18n.set_language(language="fr")


def test_mark_returns_text_untranslated(locale_dir: Path) -> None:
    i18n.set_language(language=i18n.ENGLISH, locale_dir=locale_dir)
    assert i18n.N_("Applica") == "Applica"


def test_decimal_separator_follows_language(tmp_path: Path) -> None:
    assert i18n.decimal_separator() == ","
    i18n.set_language(language=i18n.ENGLISH, locale_dir=tmp_path)
    assert i18n.decimal_separator() == "."


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({"LANG": "en_US.UTF-8"}, i18n.ENGLISH),
        ({"LANG": "en_GB.UTF-8"}, i18n.ENGLISH),
        ({"LANG": "it_IT.UTF-8"}, i18n.ITALIAN),
        ({"LANG": "de_DE.UTF-8"}, i18n.ITALIAN),
        ({"LANG": "C.UTF-8"}, i18n.ITALIAN),
        ({}, i18n.ITALIAN),
        ({"LANGUAGE": "en:it", "LANG": "it_IT.UTF-8"}, i18n.ENGLISH),
        ({"LC_ALL": "it_IT.UTF-8", "LANG": "en_US.UTF-8"}, i18n.ITALIAN),
        ({"LC_MESSAGES": "en_US.UTF-8", "LANG": "it_IT.UTF-8"}, i18n.ENGLISH),
        ({"LANGUAGE": "", "LANG": "en_US.UTF-8"}, i18n.ENGLISH),
        ({"LANGUAGE": "de:en"}, i18n.ENGLISH),
        ({"LANGUAGE": "de:it:en"}, i18n.ITALIAN),
        ({"LANGUAGE": "C"}, i18n.ITALIAN),
        ({"LANGUAGE": "C:en"}, i18n.ENGLISH),
    ],
)
def test_resolve_default_follows_first_locale_variable(
    environ: dict[str, str], expected: str
) -> None:
    assert i18n.resolve_default(environ=environ) == expected


@pytest.mark.usefixtures("english")
def test_english_fixture_loads_shipped_catalog() -> None:
    assert i18n.current_language() == i18n.ENGLISH
    assert i18n.decimal_separator() == "."
