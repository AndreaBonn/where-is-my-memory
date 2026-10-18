"""F14: the command that starts a stopped process again, quoted for a POSIX shell."""

import pytest

from wimm.core.planning_restart import restart_command


def test_restart_command_joins_cd_and_argv() -> None:
    command = restart_command(argv=("python3", "-m", "http.server", "8765"), cwd="/work/app")

    assert command == "cd -- /work/app && python3 -m http.server 8765"


def test_restart_command_quotes_spaces_in_cwd_and_arguments() -> None:
    command = restart_command(argv=("node", "my server.js"), cwd="/work/my app")

    assert command == "cd -- '/work/my app' && node 'my server.js'"


def test_restart_command_quotes_apostrophes() -> None:
    command = restart_command(argv=("echo", "it's"), cwd="/work/o'neil")

    assert command == "cd -- '/work/o'\"'\"'neil' && echo 'it'\"'\"'s'"


@pytest.mark.parametrize("argv", [None, ()])
def test_restart_command_without_argv_is_none(argv: tuple[str, ...] | None) -> None:
    assert restart_command(argv=argv, cwd="/work/app") is None


@pytest.mark.parametrize("cwd", [None, ""])
def test_restart_command_without_cwd_is_none(cwd: str | None) -> None:
    assert restart_command(argv=("node", "a.js"), cwd=cwd) is None


@pytest.mark.parametrize(
    ("argv", "cwd"),
    [
        (("echo", "a\nb"), "/work"),
        (("echo", "a\x1b[0m"), "/work"),
        (("echo", "a"), "/work\r/x"),
        (("echo", "a\x7f"), "/work"),
    ],
)
def test_restart_command_refuses_control_characters(argv: tuple[str, ...], cwd: str) -> None:
    assert restart_command(argv=argv, cwd=cwd) is None


@pytest.mark.parametrize(
    "character",
    [
        pytest.param("\u009b", id="Cc-C1-csi"),
        pytest.param("\u202e", id="Cf-bidi-override"),
        pytest.param("\u2066", id="Cf-bidi-isolate"),
        pytest.param("\u2069", id="Cf-bidi-pop-isolate"),
        pytest.param("\u200b", id="Cf-zero-width-space"),
        pytest.param("\u2028", id="Zl-line-separator"),
        pytest.param("\u2029", id="Zp-paragraph-separator"),
    ],
)
@pytest.mark.parametrize("where", ["argv", "cwd"])
def test_restart_command_refuses_invisible_and_format_characters(
    character: str, where: str
) -> None:
    argv = ("echo", f"a{character}b") if where == "argv" else ("echo", "a")
    cwd = f"/work{character}" if where == "cwd" else "/work"

    assert restart_command(argv=argv, cwd=cwd) is None


def test_restart_command_keeps_accented_letters_and_spaces() -> None:
    command = restart_command(argv=("node", "caffè è.js"), cwd="/work/perché sì")

    assert command == "cd -- '/work/perché sì' && node 'caffè è.js'"
