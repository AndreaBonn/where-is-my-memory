"""Tool output made safe to log or to put in an error message (T-6.38b)."""

import re

TAIL_CHARS = 200
_TERMINAL_ESCAPE = re.compile(
    r"\x1b(?:\][^\x07\x1b]*(?:\x07|\x1b\\)|\[[0-?]*[ -/]*[@-~]|[@-Z\\-_c])"
)
# C0 and C1 controls (U+009B is an 8-bit CSI): tab and newline stay, as word separators.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def printable(*, text: str, limit: int = TAIL_CHARS) -> str:
    """`text` without terminal escapes or control characters, one line, the last `limit` chars.

    `ollama rm` prints a spinner even without a tty, and the model name or a server message
    could carry an escape that rewrites a terminal or a log viewer.
    """
    clean = _CONTROL.sub("", _TERMINAL_ESCAPE.sub("", text.replace("\r", "\n")))
    return " ".join(clean.split())[-limit:]


# Marks, embeddings, overrides and isolates (Unicode bidi controls): they reorder the
# characters around them, so a name can display as something it is not.
_BIDI_CONTROL = re.compile("[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]")


def visible_text(*, text: str) -> str:
    """`text` on one line without controls or bidi marks: what a user can read and type.

    Process, folder and model names come from the system, and a confirmation dialog must
    not show a reordered target ("evil" U+202E "gpj.exe" displays as "evilexe.jpg").
    """
    spaced = text.replace("\t", " ").replace("\n", " ").replace("\r", " ")
    return " ".join(_CONTROL.sub("", _BIDI_CONTROL.sub("", spaced)).split())
