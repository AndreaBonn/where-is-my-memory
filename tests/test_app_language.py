import logging
import os
from pathlib import Path

import pytest

from wimm import app, i18n
from wimm.config import parse_config
from wimm.language_switch import apply_startup_language


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


def test_startup_language_reads_the_saved_choice_before_the_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from wimm.config import Config, save_config
    from wimm.paths import default_user_paths

    monkeypatch.setenv(name="LANG", value="it_IT.UTF-8")
    save_config(paths=default_user_paths(), config=Config(language="en"))
    apply_startup_language()
    assert i18n.current_language() == i18n.ENGLISH


def test_startup_language_without_config_follows_system(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in i18n.LOCALE_VARIABLES:
        monkeypatch.delenv(name=name, raising=False)
    monkeypatch.setenv(name="LANG", value="en_US.UTF-8")
    apply_startup_language()
    assert i18n.current_language() == i18n.ENGLISH


def test_startup_language_with_a_broken_config_stays_quiet(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from wimm.paths import default_user_paths

    # Logging is not set up yet: a warning here would go to stderr through lastResort.
    paths = default_user_paths()
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    (paths.config_dir / "config.json").write_text("{broken", encoding="utf-8")
    monkeypatch.setenv(name="LANGUAGE", value="en")
    with caplog.at_level(logging.DEBUG):
        apply_startup_language()
    assert i18n.current_language() == i18n.ENGLISH
    assert caplog.records == []


def test_startup_language_is_exported_for_gtk_own_texts(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in i18n.LOCALE_VARIABLES:
        monkeypatch.delenv(name=name, raising=False)
    monkeypatch.setenv(name="LANG", value="it_IT.UTF-8")
    apply_startup_language()
    # Created here, while only the main thread runs: later switches only replace it.
    assert os.environ["LANGUAGE"] == "it"


def test_language_exported_by_a_test_never_reaches_the_next(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # tests/conftest.py removes LANGUAGE around each test, even when it was absent before.
    assert "LANGUAGE" not in os.environ
    apply_startup_language()
    assert "LANGUAGE" in os.environ


def test_language_is_absent_again_in_the_next_test() -> None:
    assert "LANGUAGE" not in os.environ
