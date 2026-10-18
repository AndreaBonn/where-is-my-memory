import json
from pathlib import Path

from wimm.serialize import snapshot_from_json
from wimm.snapshot_redaction import redacted_snapshot_json

FIXTURE = Path(__file__).parent / "fixtures" / "snapshot_whitebox.json"


def test_redaction_keeps_the_growth_of_the_group_untouched() -> None:
    snapshot = snapshot_from_json(text=FIXTURE.read_text())

    group = json.loads(redacted_snapshot_json(snapshot=snapshot))["groups"][0]

    assert group["growth"] == {"delta_bytes": 620_000_000, "span_s": 7200}
