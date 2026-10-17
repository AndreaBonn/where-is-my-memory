from pathlib import Path

import pytest

from wimm import app, i18n
from wimm.config import parse_config


def test_apply_config_saved_language_wins_over_system(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(name="LANG", value="it_IT.UTF-8")
    app._apply_config(loaded=parse_config(raw={"language": "en"}, home=tmp_path))
    assert i18n.current_language() == i18n.ENGLISH


def test_apply_config_without_choice_follows_system(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in i18n.LOCALE_VARIABLES:
        monkeypatch.delenv(name=name, raising=False)
    monkeypatch.setenv(name="LANG", value="en_US.UTF-8")
    app._apply_config(loaded=parse_config(raw={}, home=tmp_path))
    assert i18n.current_language() == i18n.ENGLISH


def test_apply_config_saved_italian_on_english_system(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(name="LANGUAGE", value="en")
    app._apply_config(loaded=parse_config(raw={"language": "it"}, home=tmp_path))
    assert i18n.current_language() == i18n.ITALIAN
