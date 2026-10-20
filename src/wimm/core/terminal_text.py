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
