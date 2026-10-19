"""T-6.37b: the strict parser of `ollama list` (design note section 4)."""

from pathlib import Path

import pytest

from wimm.core.ollama_list import ListedModel, parse_ollama_list

FIXTURE = Path(__file__).parents[1] / "fixtures" / "ollama" / "list_0_18_0.txt"
HEADER = "NAME                  ID              SIZE      MODIFIED     "
GOOD_ROW = "gemma3:4b             a2af6cc3eb7f    3.3 GB    2 weeks ago     "


def _listing(*rows: str, header: str = HEADER) -> str:
    return "\n".join([header, *rows]) + "\n"


def _parse(*rows: str, header: str = HEADER) -> tuple[ListedModel, ...] | None:
    return parse_ollama_list(text=_listing(*rows, header=header))


def test_recorded_output_of_ollama_0_18_0_lists_four_models() -> None:
    text = FIXTURE.read_text(encoding="utf-8")

    models = parse_ollama_list(text=text)

    assert models is not None
    assert [m.name for m in models] == [
        "qwen3-embedding:8b",
        "gemma3:4b",
        "qwen3.5:9b",
        "qwen2.5vl:7b",
    ]
    assert {m.name: m.model_id for m in models}["gemma3:4b"] == "a2af6cc3eb7f"
    assert {m.name: m.size for m in models}["gemma3:4b"] == 3_300_000_000


def test_the_fixture_keeps_the_trailing_spaces_of_the_real_output() -> None:
    lines = FIXTURE.read_text(encoding="utf-8").splitlines()

    assert len(lines) == 5
    assert all(line != line.rstrip() for line in lines)


def test_sizes_are_decimal_and_rounded_to_whole_bytes() -> None:
    models = parse_ollama_list(text=FIXTURE.read_text(encoding="utf-8"))

    assert models is not None
    assert [m.size for m in models] == [4_700_000_000, 3_300_000_000, 6_600_000_000, 6_000_000_000]


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        ("512 B", 512),
        ("1.5 KB", 1_500),
        ("274 MB", 274_000_000),
        ("1.1 GB", 1_100_000_000),
        ("2 TB", 2_000_000_000_000),
        ("0.0 B", 0),
    ],
)
def test_every_decimal_unit_is_a_power_of_a_thousand(size: str, expected: int) -> None:
    models = _parse(f"m:1    a2af6cc3eb7f    {size}    now")

    assert models is not None and models[0].size == expected


def test_rows_without_trailing_spaces_parse_the_same() -> None:
    assert _parse(GOOD_ROW.rstrip()) == _parse(GOOD_ROW)
    assert _parse(GOOD_ROW) is not None


def test_header_only_is_an_empty_listing() -> None:
    assert _parse() == ()


def test_a_parsed_listing_is_a_tuple_of_listed_models() -> None:
    models = _parse(GOOD_ROW)

    assert models == (ListedModel(name="gemma3:4b", model_id="a2af6cc3eb7f", size=3_300_000_000),)


@pytest.mark.parametrize(
    "header",
    [
        "NAME ID SIZE",
        "NAME ID SIZE MODIFIED EXTRA",
        "name id size modified",
        "ID NAME SIZE MODIFIED",
        "NOME ID DIMENSIONE MODIFICATO",
    ],
)
def test_a_changed_header_rejects_the_whole_output(header: str) -> None:
    assert _parse(GOOD_ROW, header=header) is None
    assert _parse(GOOD_ROW) is not None


@pytest.mark.parametrize(
    "row",
    [
        "gemma3:4b    a2af6cc3eb7    3.3 GB    2 weeks ago",
        "gemma3:4b    a2af6cc3eb7ff    3.3 GB    2 weeks ago",
        "gemma3:4b    A2AF6CC3EB7F    3.3 GB    2 weeks ago",
        "-rf:x    a2af6cc3eb7f    3.3 GB    2 weeks ago",
        "gem\x1bma:4b    a2af6cc3eb7f    3.3 GB    2 weeks ago",
        "gemma3    a2af6cc3eb7f    3.3 GB    2 weeks ago",
        "gemma3:4b    a2af6cc3eb7f    3.3 GiB    2 weeks ago",
        "gemma3:4b    a2af6cc3eb7f    3.3 gb    2 weeks ago",
        "gemma3:4b    a2af6cc3eb7f    3,3 GB    2 weeks ago",
        "gemma3:4b    a2af6cc3eb7f    GB    2 weeks ago",
        "gemma3:4b    a2af6cc3eb7f    3.3 GB",
        "gemma3:4b    a2af6cc3eb7f",
        "  gemma3:4b    a2af6cc3eb7f    3.3 GB    2 weeks ago",
        "",
    ],
)
def test_one_bad_row_rejects_the_whole_output(row: str) -> None:
    assert _parse(GOOD_ROW, row) is None
    assert _parse(GOOD_ROW) is not None


def test_a_bad_row_in_the_middle_does_not_leave_a_partial_list() -> None:
    other = "qwen3.5:9b    6488c96fa5fa    6.6 GB    2 weeks ago"

    assert _parse(GOOD_ROW, "garbage", other) is None
    assert _parse(GOOD_ROW, other) is not None


def test_duplicate_names_reject_the_whole_output() -> None:
    twin = "gemma3:4b    6488c96fa5fa    6.6 GB    2 weeks ago"

    assert _parse(GOOD_ROW, twin) is None


@pytest.mark.parametrize("text", ["", "\n", "   \n", "Error: could not connect to ollama server\n"])
def test_output_without_the_header_is_rejected(text: str) -> None:
    assert parse_ollama_list(text=text) is None


def test_the_error_message_of_an_unreachable_server_is_not_a_listing() -> None:
    text = "Error: could not connect to ollama server, run 'ollama serve' to start it\n"

    assert parse_ollama_list(text=text) is None
