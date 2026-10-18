"""The `ollama serve` predicate: binary name and the `serve` argument, nothing looser."""

import pytest

from wimm.core.ollama_serve import is_ollama_serve


@pytest.mark.parametrize(
    ("name", "argv"),
    [
        ("ollama", ["/usr/local/bin/ollama", "serve"]),
        ("ollama", ["ollama", "serve"]),
        ("ollama", ["/usr/bin/ollama", "--verbose", "serve"]),
        ("ollama", ["ollama: worker", "serve"]),
    ],
)
def test_is_ollama_serve_true_for_the_server(name: str, argv: list[str]) -> None:
    assert is_ollama_serve(name=name, argv=argv) is True


def test_is_ollama_serve_uses_argv0_when_the_process_name_is_truncated() -> None:
    assert is_ollama_serve(name="ollama-ser", argv=["/usr/local/bin/ollama", "serve"]) is True


@pytest.mark.parametrize(
    ("name", "argv"),
    [
        ("ollama", ["/usr/local/bin/ollama", "run", "llama3"]),
        ("ollama", ["ollama", "list"]),
        ("ollama", ["ollama"]),
        ("ollama", ["serve"]),
        ("python3", ["python3", "/home/u/ollama/serve.py", "serve"]),
        ("vim", ["vim", "/home/u/.ollama/notes", "serve"]),
        ("ollama-tool", ["/opt/ollama-tool", "serve"]),
        ("", []),
    ],
)
def test_is_ollama_serve_false_when_not_the_server(name: str, argv: list[str]) -> None:
    assert is_ollama_serve(name=name, argv=argv) is False


def test_is_ollama_serve_counts_an_ollama_whose_arguments_are_unreadable() -> None:
    # psutil leaves the command line empty when it cannot read it: refuse rather than clean.
    assert is_ollama_serve(name="ollama", argv=[]) is True
