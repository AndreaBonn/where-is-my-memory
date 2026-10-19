import json
import re
from typing import Any, cast

import pytest

from tests.helpers import invalid_model_value
from tests.serialize_helpers import FIXTURE, set_path
from wimm.serialize import snapshot_from_json


@pytest.fixture
def document() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(FIXTURE.read_text()))


def dotted(path: tuple[str | int, ...]) -> str:
    """The location the decoder reports: ``snapshot.groups[0].members[1].create_time``."""
    return "snapshot" + "".join(f"[{key}]" if isinstance(key, int) else f".{key}" for key in path)


def test_dotted_reports_keys_with_dots_and_indexes_with_brackets() -> None:
    assert dotted(("groups", 0, "members", 1, "create_time")) == (
        "snapshot.groups[0].members[1].create_time"
    )


@pytest.mark.parametrize(
    "path,value",
    [
        (("schema",), 1),
        (("schema",), 2),
        (("schema",), 3),
        (("schema",), 5),
        (("schema",), True),
        (("schema",), 1.0),
        (("pressure",), "bad"),
        (("pressure",), 1),
        (("taken_at",), "2026-10-16T10:30:00"),
        (("taken_at",), 123),
        (("groups",), {}),
        (("docker", "available"), 1),
        (("memory", "total"), 1.5),
        (("memory", "used"), -1),
        (("disk", "free"), True),
        (("groups", 0, "category"), "project"),
        (("groups", 0, "protection"), "bad"),
        (("groups", 0, "protection"), "protected"),
        (("groups", 0, "ignored"), "false"),
        (("groups", 0, "compose_project"), 1),
        (("groups", 0, "ports", 0), "8000"),
        (("groups", 0, "name"), None),
        (("groups", 0, "activity", "state"), "bad"),
        (("groups", 0, "activity", "since"), None),
        (("groups", 0, "primary_action", "risk"), "bad"),
        (("groups", 0, "primary_action", "risk"), 0),
        (("groups", 0, "primary_action", "kind"), "stop_group"),
        (("groups", 0, "members", 0, "kind"), "other"),
        (("groups", 0, "members", 1, "create_time"), True),
        (("groups", 0, "members", 1, "create_time"), "1760590000.12"),
        (("memory", "breakdown", "kernel_cache"), -1),
    ],
)
def test_decoder_rejects_bad_values_with_field_path(
    document: dict[str, Any], path: tuple[str | int, ...], value: object
) -> None:
    assert snapshot_from_json(text=json.dumps(document)).groups[0].name == "whitebox"
    set_path(document=document, path=path, value=value)
    # A rule across fields (protection vs category, since vs state) is reported on the record.
    at_field = f"{re.escape(dotted(path))}[: ]"
    at_record = f"{re.escape(dotted(path[:-1]))}: {path[-1]} "
    with pytest.raises(ValueError, match=f"{at_field}|{at_record}"):
        snapshot_from_json(text=json.dumps(document))


OBJECT_PATHS: list[tuple[str | int, ...]] = [
    (),
    ("memory",),
    ("memory", "breakdown"),
    ("disk",),
    ("reclaimable_now",),
    ("docker",),
    ("groups", 0),
    ("groups", 0, "activity"),
    ("groups", 0, "memory"),
    ("groups", 0, "primary_action"),
    ("groups", 0, "members", 0),
    ("groups", 0, "members", 1),
    ("groups", 0, "members", 0, "mounts", 0),
    ("protected_summary", 0),
]


@pytest.mark.parametrize("path", OBJECT_PATHS)
@pytest.mark.parametrize("operation", ["missing", "unknown", "wrong_type"])
def test_decoder_checks_object_fields_at_every_level(
    document: dict[str, Any], path: tuple[str | int, ...], operation: str
) -> None:
    assert snapshot_from_json(text=json.dumps(document)).pressure.value == "warning"
    target: Any = document
    for key in path:
        target = (
            cast(dict[str, Any], target)[key]
            if isinstance(key, str)
            else cast(list[Any], target)[key]
        )
    field = "kernel_cache" if path == ("memory", "breakdown") else next(iter(target))
    if operation == "missing":
        del target[field]
    elif operation == "unknown":
        target["unexpected"] = 1
        field = "unexpected"
    elif path:
        set_path(document=document, path=path, value=[])
        field = str(path[-1])
    else:
        document = invalid_model_value([])
        field = "snapshot"
    with pytest.raises(ValueError, match=field):
        snapshot_from_json(text=json.dumps(document))


@pytest.mark.parametrize("text", ["{", "null", "[]", "42", '{"schema":NaN}', '{"schema":Infinity}'])
def test_decoder_rejects_malformed_document(text: str) -> None:
    assert snapshot_from_json(text=FIXTURE.read_text()).groups[0].name == "whitebox"
    with pytest.raises(ValueError):
        snapshot_from_json(text=text)
