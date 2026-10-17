from pathlib import Path

import pytest

from wimm.config_roots import (
    decode_roots,
    default_roots,
    expand_root,
    missing_roots,
    validate_roots,
)


def test_expand_root_handles_tilde_and_absolute(tmp_path: Path) -> None:
    assert expand_root(value="~", home=tmp_path) == tmp_path.resolve()
    assert expand_root(value="~/a", home=tmp_path) == (tmp_path / "a").resolve()
    assert expand_root(value=str(tmp_path / "b"), home=tmp_path) == (tmp_path / "b").resolve()


@pytest.mark.parametrize("value", ["", "relative/dir"])
def test_expand_root_rejects_empty_and_relative(tmp_path: Path, value: str) -> None:
    with pytest.raises(ValueError):
        expand_root(value=value, home=tmp_path)


def test_default_roots_come_from_detection(tmp_path: Path) -> None:
    (tmp_path / "code" / "app" / ".git").mkdir(parents=True)
    (tmp_path / "Documents" / "photos").mkdir(parents=True)
    assert default_roots(home=tmp_path) == ((tmp_path / "code").resolve(),)


def test_default_roots_are_empty_when_nothing_is_detected(tmp_path: Path) -> None:
    assert default_roots(home=tmp_path) == ()


def test_decode_roots_accepts_existing_dir_within_home(tmp_path: Path) -> None:
    (tmp_path / "code").mkdir()
    assert decode_roots(value=["~/code"], home=tmp_path) == ((tmp_path / "code").resolve(),)


@pytest.mark.parametrize("value", [[], ["/"], ["/nonexistent/elsewhere"], ["~/../other"]])
def test_decode_roots_rejects_empty_and_outside_home(tmp_path: Path, value: list[str]) -> None:
    with pytest.raises(ValueError):
        decode_roots(value=value, home=tmp_path)


@pytest.mark.parametrize("roots", [[Path("/a")], [], (Path("rel"),), ("/a",)])
def test_validate_roots_rejects_non_tuple_relative_or_str(roots: object) -> None:
    with pytest.raises(ValueError):
        validate_roots(roots=roots)


def test_validate_roots_accepts_tuple_of_absolute_paths() -> None:
    validate_roots(roots=(Path("/a"),))


def test_validate_roots_accepts_the_empty_tuple_of_an_empty_detection() -> None:
    validate_roots(roots=())


def test_decode_roots_keeps_a_missing_root_within_home(tmp_path: Path) -> None:
    (tmp_path / "code").mkdir()
    decoded = decode_roots(value=["~/gone", "~/code"], home=tmp_path)
    assert decoded == ((tmp_path / "gone").resolve(), (tmp_path / "code").resolve())


def test_decode_roots_rejects_a_root_that_is_a_file(tmp_path: Path) -> None:
    (tmp_path / "file").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        decode_roots(value=["~/file"], home=tmp_path)


def test_missing_roots_lists_only_roots_that_are_not_directories(tmp_path: Path) -> None:
    (tmp_path / "code").mkdir()
    roots = (tmp_path / "gone", tmp_path / "code")
    assert missing_roots(roots=roots) == (tmp_path / "gone",)
    assert missing_roots(roots=(tmp_path / "code",)) == ()
