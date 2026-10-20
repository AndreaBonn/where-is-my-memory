"""T-6.38b: tool output reaches a log or an error message without terminal control."""

import pytest

from wimm.core.terminal_text import printable, visible_text

SPINNER = "\x1b[?25l\x1b[?2026h\x1b[1G⠋ \x1b[K\x1b[?25h\x1b[?2026l\x1b[2K\x1b[1G"
SPINNER += "Error: model 'x' not found"


def test_the_escapes_of_a_spinner_are_removed_and_the_message_stays() -> None:
    assert printable(text=SPINNER) == "⠋ Error: model 'x' not found"


@pytest.mark.parametrize(
    ("text", "clean"),
    [
        ("plain text", "plain text"),
        ("a\x00b\x07c\x7fd", "abcd"),
        # C1 controls: U+009B is an 8-bit CSI; U+0085 would otherwise split as a space.
        ("a\x9b2Jb\x85c\x80d", "a2Jbcd"),
        ("caffè · ⠋", "caffè · ⠋"),
        ("one\r\ntwo\rthree\n\nfour", "one two three four"),
        ("\x1b]0;title\x07after", "after"),
        ("\x1b]8;;http://e\x1b\\link\x1b]8;;\x1b\\", "link"),
        ("\x1bcreset", "reset"),
        ("  padded \t words  ", "padded words"),
        ("", ""),
    ],
)
def test_control_characters_and_odd_spacing_are_cleaned(text: str, clean: str) -> None:
    assert printable(text=text) == clean


def test_a_long_output_keeps_its_tail() -> None:
    assert printable(text="head " + "x" * 300 + " tail", limit=20) == "x" * 15 + " tail"


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        # U+202E reverses what follows: "evil\u202egpj.exe" displays as "evilexe.jpg".
        ("evil\u202egpj.exe", "evilgpj.exe"),
        ("\u2067postgres\u2069", "postgres"),
        ("a\u200eb\u200fc\u061cd\u202ae\u202cf", "abcdef"),
        ("one\ntwo\tthree\x00\x1b", "one two three"),
        # Letters of a right-to-left script and accents are text, not controls.
        ("مدل · caffè", "مدل · caffè"),
        ("plain", "plain"),
    ],
)
def test_visible_text_drops_bidi_and_control_characters(text: str, shown: str) -> None:
    assert visible_text(text=text) == shown
