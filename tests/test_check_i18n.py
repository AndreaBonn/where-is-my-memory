from pathlib import Path

import pytest

from scripts.check_i18n import is_text, lost_terms, scan_source

SOURCE = Path("/repo/src/wimm/ui/example.py")


def flagged(source: str, path: Path = SOURCE) -> list[str]:
    return [finding.text for finding in scan_source(path=path, source=source)]


@pytest.mark.parametrize(
    "text", ["Esci", "Ferma il progetto", "Memoria usata {}%", "Docker", "Altri filtri"]
)
def test_is_text_true_for_words_a_person_reads(text: str) -> None:
    assert is_text(text=text)


@pytest.mark.parametrize(
    "text",
    [
        "win.preferences",
        "open-menu-symbolic",
        "io.github.wimm.Inspector1",
        "/io/github/wimm/Inspector",
        "~/Documenti/00_Lavoro",
        "SystemServices",
        "PLAN_EXPIRED",
        "{name} ({size})",
        "MB",
        r"(?:key|token)\s*",
        "\n.bar { color: red; }\n",
        "<node><interface/></node>",
    ],
)
def test_is_text_false_for_names_formats_and_code(text: str) -> None:
    assert not is_text(text=text)


def test_scan_flags_a_label_outside_gettext_and_not_one_inside() -> None:
    source = 'label = Gtk.Label(label="Esci")\nother = Gtk.Label(label=_("Applica"))\n'
    assert flagged(source) == ["Esci"]


def test_scan_flags_italian_fstrings_but_not_marked_templates() -> None:
    source = 'a = f"{n} giorni fa"\nb = _("{n} giorni fa").format(n=n)\nc = N_("Ferma")\n'
    assert flagged(source) == ["{} giorni fa"]


def test_scan_skips_docstrings_and_log_calls_but_not_the_code_next_to_them() -> None:
    source = (
        '"""Modulo con testo."""\n'
        "class Row:\n"
        '    """Una riga della lista."""\n'
        '    TITLE = "Titolo visibile"\n'
        "def show():\n"
        '    """Mostra la riga."""\n'
        '    LOGGER.warning("Cannot show the row %s", name)\n'
        '    return "Riga mostrata"\n'
    )
    assert flagged(source) == ["Titolo visibile", "Riga mostrata"]


def test_scan_reports_only_italian_inside_raise() -> None:
    source = (
        'raise ValueError(f"{name}: below range or non-finite")\n'
        'raise ValueError("Il valore non è valido")\n'
    )
    assert flagged(source) == ["Il valore non è valido"]


def test_scan_skips_internal_error_attributes_but_not_the_user_message() -> None:
    source = (
        "class Failed(WimmError):\n"
        '    code = "FAILED"\n'
        '    message = "System call failed"\n'
        '    user_message = "Operazione non riuscita"\n'
    )
    assert flagged(source) == ["Operazione non riuscita"]


def test_scan_exempts_listed_strings_only_in_their_file() -> None:
    source = 'CHOICES = (("it", "Italiano"),)\n'
    exempt_file = Path("/repo/src/wimm/ui/dialogs/preferences_language.py")
    assert flagged(source, path=exempt_file) == []
    assert flagged(source) == ["Italiano"]


def test_lost_terms_finds_a_dropped_shared_term_by_whole_word() -> None:
    assert lost_terms(msgid="Ferma il container", msgstr="Stop the box") == ["container"]
    assert lost_terms(msgid="Ferma il container", msgstr="Stop the container") == []
    # "programmi" contains "ram" but is not the term RAM.
    assert lost_terms(msgid="programmi di sviluppo", msgstr="development programs") == []


def test_scan_flags_a_single_word_next_to_a_placeholder() -> None:
    source = 'a = f"{n} processi"\nb = "processi"\n'
    # A bare lowercase word may be a name; next to a value it is a sentence.
    assert flagged(source) == ["{} processi"]
