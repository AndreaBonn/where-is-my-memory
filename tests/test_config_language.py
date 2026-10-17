from pathlib import Path

import pytest

from wimm.config import Config, load_config, parse_config, save_config, update_config
from wimm.paths import UserPaths


@pytest.fixture
def paths(tmp_path: Path) -> UserPaths:
    return UserPaths(
        config_dir=tmp_path / "config", state_dir=tmp_path / "state", cache_dir=tmp_path / "cache"
    )


def test_language_defaults_to_none_meaning_system(tmp_path: Path) -> None:
    assert parse_config(raw={}, home=tmp_path).config.language is None


@pytest.mark.parametrize("language", ["it", "en"])
def test_language_valid_value_is_kept(language: str, tmp_path: Path) -> None:
    parsed = parse_config(raw={"language": language}, home=tmp_path)
    assert parsed.config.language == language
    assert parsed.field_errors == {}


@pytest.mark.parametrize("value", ["fr", "", 1, ["en"], "EN"])
def test_language_invalid_value_gives_field_error_and_default(
    value: object, tmp_path: Path
) -> None:
    parsed = parse_config(raw={"language": value}, home=tmp_path)
    assert parsed.config.language is None
    assert set(parsed.field_errors) == {"language"}


def test_language_explicit_null_is_system_default(tmp_path: Path) -> None:
    parsed = parse_config(raw={"language": None}, home=tmp_path)
    assert parsed.config.language is None
    assert parsed.field_errors == {}


def test_language_constructor_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="language"):
        Config(language="fr")


def test_language_survives_save_and_load(paths: UserPaths, tmp_path: Path) -> None:
    changed = update_config(config=Config(), changes={"language": "en"}, home=tmp_path)
    save_config(paths=paths, config=changed.config)
    assert load_config(paths=paths, home=tmp_path).config.language == "en"
