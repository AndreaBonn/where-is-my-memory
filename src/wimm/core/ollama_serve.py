"""Recognise the ollama server among processes (R24), from name and arguments only."""

from collections.abc import Sequence
from pathlib import PurePosixPath

from .constants import OLLAMA_NAME

OLLAMA_SERVE_ARGUMENT = "serve"


def _is_ollama_binary(*, name: str, argv: Sequence[str]) -> bool:
    """The process name or the basename of the first argument is exactly `ollama`."""
    first = PurePosixPath(argv[0]).name if argv else ""
    return OLLAMA_NAME in (name, first)


def is_ollama_serve(*, name: str, argv: Sequence[str]) -> bool:
    """True for `ollama serve`: the binary is `ollama` and one argument is `serve`.

    `ollama` alone in a path (`/home/u/.ollama/...`) or `ollama run` / `ollama list` do not count.
    A process named `ollama` whose command line could not be read (empty ``argv``) counts:
    refusing a clean is the safe side of not knowing.
    """
    if name == OLLAMA_NAME and not argv:
        return True
    return _is_ollama_binary(name=name, argv=argv) and OLLAMA_SERVE_ARGUMENT in argv[1:]
