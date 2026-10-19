"""Strict parser of `ollama list` (T-6.37b, design note section 4).

One row outside the schema rejects the whole output: a partial list would understate the
store without saying so, and a format changed by a new ollama must show as absence, not as
wrong data.
"""

import re
from dataclasses import dataclass
from typing import Final

from .ollama_names import is_valid_model_name

HEADER_COLUMNS: Final = ("NAME", "ID", "SIZE", "MODIFIED")
UNIT_POWERS: Final = {"B": 0, "KB": 1, "MB": 2, "GB": 3, "TB": 4}
DECIMAL_BASE: Final = 1000
ROW_PATTERN: Final = re.compile(
    r"(?P<name>\S+)\s+(?P<id>[0-9a-f]{12})\s+"
    r"(?P<num>\d+(?:\.\d+)?) (?P<unit>B|KB|MB|GB|TB)\s+\S.*"
)


@dataclass(frozen=True, slots=True)
class ListedModel:
    """One row: the name `ollama rm` takes, the 12-hex id, and the size in bytes (estimated)."""

    name: str
    model_id: str
    size: int


def _parse_row(*, line: str) -> ListedModel | None:
    match = ROW_PATTERN.fullmatch(line.rstrip())
    if match is None or not is_valid_model_name(name=match["name"]):
        return None
    size = round(float(match["num"]) * DECIMAL_BASE ** UNIT_POWERS[match["unit"]])
    return ListedModel(name=match["name"], model_id=match["id"], size=size)


def parse_ollama_list(*, text: str) -> tuple[ListedModel, ...] | None:
    """The models of an `ollama list` output; empty for the header alone, None if malformed."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not lines or tuple(lines[0].split()) != HEADER_COLUMNS:
        return None
    models = [_parse_row(line=line) for line in lines[1:]]
    found = [model for model in models if model is not None]
    if len(found) != len(models) or len({m.name for m in found}) != len(found):
        return None
    return tuple(found)
