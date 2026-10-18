from pathlib import Path

import pytest

from wimm.config import parse_config
from wimm.config_messages import root_refusal_message
from wimm.core.root_policy import RootRefusal

INVALID = {
    "sample_interval_s": 1,
    "cpu_active_threshold_pct": 999.0,
    "notify_min_bytes": -1,
    "devdirs_max_depth": 99,
    "notify_categories": ["SYSTEM"],
    "foreground_tracking": 1,
    "language": "fr",
}


def errors(*, home: Path, raw: dict[str, object]) -> dict[str, str]:
    return dict(parse_config(raw=raw, home=home).field_errors)


def test_field_errors_read_in_italian(tmp_path: Path) -> None:
    assert errors(home=tmp_path, raw=INVALID) == {
        "sample_interval_s": "Deve essere un numero intero fra 10 e 300 secondi",
        "cpu_active_threshold_pct": "Deve essere un numero fra 0.1 e 50",
        "notify_min_bytes": "Deve essere un numero intero almeno 0",
        "devdirs_max_depth": "Deve essere un numero intero fra 1 e 12",
        "notify_categories": "Scegli solo categorie su cui sono consentite azioni",
        "foreground_tracking": "Deve essere un valore booleano",
        "language": "Scegli una lingua disponibile",
    }


@pytest.mark.usefixtures("english")
def test_field_errors_read_in_english(tmp_path: Path) -> None:
    assert errors(home=tmp_path, raw=INVALID) == {
        "sample_interval_s": "Must be a whole number between 10 and 300 seconds",
        "cpu_active_threshold_pct": "Must be a number between 0.1 and 50",
        "notify_min_bytes": "Must be a whole number, at least 0",
        "devdirs_max_depth": "Must be a whole number between 1 and 12",
        "notify_categories": "Choose only categories that allow actions",
        "foreground_tracking": "Must be true or false",
        "language": "Choose an available language",
    }


@pytest.mark.usefixtures("english")
def test_pressure_conflict_reads_in_english(tmp_path: Path) -> None:
    raw: dict[str, object] = {"pressure_warning_pct": 10, "pressure_critical_pct": 20}
    assert errors(home=tmp_path, raw=raw) == {
        "pressure_critical_pct": "Must be lower than the warning threshold"
    }


def test_every_refusal_reads_in_italian_and_the_reasons_differ() -> None:
    texts = {reason: root_refusal_message(reason=reason) for reason in RootRefusal}
    assert texts[RootRefusal.NOT_OWNED] == "La cartella non è tua"
    assert len(set(texts.values())) == len(RootRefusal)
