"""Snapshot JSON with the command lines redacted, shared by the D-Bus inspector and the CLI.

No ``gi`` import: ``wimm status`` must stay free of GTK (S12).
"""

import json
from typing import Any

from wimm.model.snapshot import Snapshot
from wimm.redaction import REDACTED, SECRET_ARGUMENT, redact_text
from wimm.serialize import snapshot_to_json


def redact_cmdline(*, arguments: list[str]) -> list[str]:
    result: list[str] = []
    pending = False
    for argument in arguments:
        if pending:
            result.append(REDACTED)
            pending = False
            continue
        match = SECRET_ARGUMENT.search(string=f"{argument} {REDACTED}")
        if match is None:
            result.append(redact_text(text=argument))
            continue
        prefix = match["prefix"]
        pending = prefix.rstrip() == argument
        result.append(argument if pending else argument[: match.start()] + prefix + REDACTED)
    return result


# Paths and labels can carry a URL with credentials or a token in a folder name.
REDACTED_TEXT_FIELDS = ("name", "explanation", "cwd", "tool_reason", "compose_project")


def _redact_fields(*, entry: dict[str, Any]) -> None:
    for field in REDACTED_TEXT_FIELDS:
        if isinstance(entry.get(field), str):
            entry[field] = redact_text(text=entry[field])


def redacted_snapshot_json(*, snapshot: Snapshot) -> str:
    """Encode ``snapshot`` with credentials removed from command lines, names and explanations."""
    data = json.loads(snapshot_to_json(snapshot=snapshot))
    for group in data["groups"]:
        _redact_fields(entry=group)
        for member in group["members"]:
            _redact_fields(entry=member)
            if "cmdline" in member:
                member["cmdline"] = redact_cmdline(arguments=member["cmdline"])
    return json.dumps(data, ensure_ascii=False)
