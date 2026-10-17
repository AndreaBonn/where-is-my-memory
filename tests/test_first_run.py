"""A1: the welcome appears once, the first time, even when started in the background."""

from pathlib import Path

import pytest

from wimm.first_run import is_first_run, mark_welcomed, opens_window


def test_a_fresh_state_directory_is_a_first_run_until_welcomed(tmp_path: Path) -> None:
    state_dir = tmp_path / "state" / "where-is-my-memory"
    assert is_first_run(state_dir=state_dir)

    mark_welcomed(state_dir=state_dir)

    assert not is_first_run(state_dir=state_dir)


def test_the_first_run_opens_the_window_even_in_the_background(tmp_path: Path) -> None:
    assert opens_window(background=False, state_dir=tmp_path)
    assert opens_window(background=True, state_dir=tmp_path)

    mark_welcomed(state_dir=tmp_path)

    assert opens_window(background=False, state_dir=tmp_path)
    assert not opens_window(background=True, state_dir=tmp_path)


def test_a_state_directory_that_cannot_be_written_is_logged_not_raised(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("")

    mark_welcomed(state_dir=blocker / "state")

    assert "Cannot remember the welcome" in caplog.text


def test_a_state_directory_that_cannot_be_read_does_not_count_as_first_run(
    tmp_path: Path,
) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0)
    try:
        assert not is_first_run(state_dir=locked / "inner")
        assert not opens_window(background=True, state_dir=locked / "inner")
    finally:
        locked.chmod(0o700)
