"""T-6.37b: which model names may reach an argv (design note section 4)."""

import pytest

from wimm.core.ollama_names import is_valid_model_name

MAX_NAME = 255
MAX_TAG = 128


@pytest.mark.parametrize(
    "name",
    [
        "gemma3:4b",
        "qwen2.5vl:7b",
        "qwen3-embedding:8b",
        "library/gemma3:latest",
        "hf.co/user/model:Q4_K_M",
        "registry.example.com/ns/name:tag",
        "A1:_x",
    ],
)
def test_real_world_names_are_valid(name: str) -> None:
    assert is_valid_model_name(name=name)


@pytest.mark.parametrize(
    "name",
    [
        "",
        "gemma3",
        "-rf:x",
        "ns/-rf:x",
        "gemma3:-x",
        "gemma3: 4b",
        "gemma 3:4b",
        "gemma3:4b ",
        "gemma3:4b\n",
        "gem\x1bma:4b",
        "gem\x00ma:4b",
        "a/../b:1",
        "..:x",
        ".hidden:1",
        "a//b:1",
        "a/b/c/d:1",
        "localhost:5000/ns/model:1",
        "a:b:c",
        "modèle:1",
        "a/b:ta/g",
    ],
)
def test_names_that_could_become_an_option_or_a_path_are_rejected(name: str) -> None:
    assert not is_valid_model_name(name=name)


def test_total_length_is_limited_to_255() -> None:
    at_limit = "a" * (MAX_NAME - 2) + ":1"
    over = "a" * (MAX_NAME - 1) + ":1"

    assert len(at_limit) == MAX_NAME and is_valid_model_name(name=at_limit)
    assert len(over) == MAX_NAME + 1 and not is_valid_model_name(name=over)


def test_tag_is_limited_to_128_characters() -> None:
    assert is_valid_model_name(name="m:" + "t" * MAX_TAG)
    assert not is_valid_model_name(name="m:" + "t" * (MAX_TAG + 1))
