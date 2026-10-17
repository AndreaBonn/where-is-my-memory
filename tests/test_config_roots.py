from pathlib import Path

import pytest

from wimm.config_roots import decode_roots, default_roots, expand_root, validate_roots


def test_expand_root_handles_tilde_and_absolute(tmp_path: Path) -> None:
    assert expand_root(value="~", home=tmp_path) == tmp_path.resolve()
    assert expand_root(value="~/a", home=tmp_path) == (tmp_path / "a").resolve()
    assert expand_root(value=str(tmp_path / "b"), home=tmp_path) == (tmp_path / "b").resolve()


@pytest.mark.parametrize("value", ["", "relative/dir"])
def test_expand_root_rejects_empty_and_relative(tmp_path: Path, value: str) -> None:
    with pytest.raises(ValueError):
        expand_root(value=value, home=tmp_path)


def test_default_roots_are_expanded_against_home(tmp_path: Path) -> None:
    assert default_roots(home=tmp_path) == ((tmp_path / "Documenti" / "00_Lavoro").resolve(),)


def test_decode_roots_accepts_existing_dir_within_home(tmp_path: Path) -> None:
    (tmp_path / "code").mkdir()
    assert decode_roots(value=["~/code"], home=tmp_path) == ((tmp_path / "code").resolve(),)


@pytest.mark.parametrize("value", [[], ["~/missing"], ["/"]])
def test_decode_roots_rejects_empty_missing_and_outside_home(
    tmp_path: Path, value: list[str]
) -> None:
    with pytest.raises(ValueError):
        decode_roots(value=value, home=tmp_path)


@pytest.mark.parametrize("roots", [[Path("/a")], (), (Path("rel"),), ("/a",)])
def test_validate_roots_rejects_non_tuple_empty_relative_or_str(roots: object) -> None:
    with pytest.raises(ValueError):
        validate_roots(roots=roots)


def test_validate_roots_accepts_tuple_of_absolute_paths() -> None:
    validate_roots(roots=(Path("/a"),))
