"""T-6.39: `ollama_served` is an optional report field, so the schema stays at 5."""

import json
from dataclasses import replace

import pytest

from wimm.core.disk_wire import disk_report_from_json, disk_report_to_json
from wimm.core.ollama_served import ServedStore
from wimm.model import SCHEMA_VERSION
from wimm.wire_decoders import SnapshotFormatError

from .disk_helpers import report


def test_a_report_with_the_situation_round_trips() -> None:
    original = replace(report(), ollama_served=ServedStore.SYSTEM.value)
    text = disk_report_to_json(report=original)
    assert json.loads(text)["ollama_served"] == "system"
    assert disk_report_from_json(text=text) == original


def test_a_report_without_it_leaves_the_field_out_and_decodes_to_empty() -> None:
    text = disk_report_to_json(report=report())
    document = json.loads(text)
    assert "ollama_served" not in document
    assert document["schema"] == SCHEMA_VERSION == 5
    assert disk_report_from_json(text=text).ollama_served == ""


def test_the_field_must_be_text() -> None:
    document = json.loads(disk_report_to_json(report=report()))
    document["ollama_served"] = 3
    with pytest.raises(SnapshotFormatError):
        disk_report_from_json(text=json.dumps(document))
