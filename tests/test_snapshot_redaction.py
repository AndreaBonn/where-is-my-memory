import json
from dataclasses import replace
from typing import Any

import pytest

from tests.tray.menu_helpers import base_snapshot, make_group
from wimm.model.snapshot import ProcessMember
from wimm.redaction import REDACTED
from wimm.snapshot_redaction import redacted_snapshot_json

SECRET_URL = "https://user:hunter2@example.com/repo"  # noqa: S105
PUBLIC_TEXT = "plain label"
REDACTED_URL = f"https://user:{REDACTED}@example.com/repo"


def _member(*, tool_reason: str) -> ProcessMember:
    group = base_snapshot().groups[0]
    template = next(m for m in group.members if isinstance(m, ProcessMember))
    return replace(template, tool_reason=tool_reason)


def _snapshot_json(*, text: str, member_reason: str) -> dict[str, Any]:
    group = replace(
        make_group("api", reclaimable=1),
        explanation=text,
        compose_project=text,
        members=(_member(tool_reason=member_reason),),
    )
    snapshot = replace(base_snapshot(), groups=(group,))
    groups: dict[str, Any] = json.loads(redacted_snapshot_json(snapshot=snapshot))["groups"][0]
    return groups


@pytest.mark.parametrize("field", ["explanation", "compose_project"])
def test_redacted_snapshot_masks_secrets_in_group_text_fields(field: str) -> None:
    group = _snapshot_json(text=SECRET_URL, member_reason=PUBLIC_TEXT)
    assert group[field] == REDACTED_URL


def test_redacted_snapshot_masks_secrets_in_member_tool_reason() -> None:
    group = _snapshot_json(text=PUBLIC_TEXT, member_reason=SECRET_URL)
    assert group["members"][0]["tool_reason"] == REDACTED_URL


def test_redacted_snapshot_keeps_text_fields_without_secrets() -> None:
    group = _snapshot_json(text=PUBLIC_TEXT, member_reason=PUBLIC_TEXT)
    assert group["explanation"] == PUBLIC_TEXT
    assert group["compose_project"] == PUBLIC_TEXT
    assert group["members"][0]["tool_reason"] == PUBLIC_TEXT
