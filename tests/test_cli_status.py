import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest
from gi.repository import GLib

from wimm import model as m
from wimm.cli_status import (
    EXIT_NO_STATE,
    EXIT_OK,
    PROXY_TIMEOUT_MS,
    StatusSources,
    run_status,
    snapshot_from_instance,
)
from wimm.cli_status_text import printable
from wimm.serialize import snapshot_from_json, snapshot_to_json
from wimm.snapshot_redaction import redacted_snapshot_json

FIXTURE = Path(__file__).parent / "fixtures" / "snapshot_whitebox.json"
LEAKED_VALUE = "hunter2-top-secret"


@pytest.fixture
def snapshot() -> m.Snapshot:
    return snapshot_from_json(text=FIXTURE.read_text())


def with_secret_cmdline(snapshot: m.Snapshot) -> m.Snapshot:
    group = snapshot.groups[0]
    process = group.members[1]
    assert isinstance(process, m.ProcessMember)
    leaking = replace(
        process, cmdline=("uvicorn", "--token", LEAKED_VALUE, "--password=" + LEAKED_VALUE)
    )
    return replace(snapshot, groups=(replace(group, members=(group.members[0], leaking)),))


class FakeProxy:
    def __init__(self, *, reply: str | None = None, error: GLib.Error | None = None) -> None:
        self.reply, self.error = reply, error
        self.calls: list[tuple[str, int]] = []

    def call_sync(
        self, method: str, parameters: object, flags: int, timeout: int, cancel: object
    ) -> GLib.Variant:
        self.calls.append((method, timeout))
        if self.error is not None:
            raise self.error
        return GLib.Variant("(s)", (self.reply,))


def test_instance_snapshot_is_returned_as_the_instance_sent_it(snapshot: m.Snapshot) -> None:
    proxy = FakeProxy(reply=snapshot_to_json(snapshot=snapshot))
    assert snapshot_from_instance(connect=lambda: proxy) == snapshot
    assert proxy.calls == [("GetSnapshot", PROXY_TIMEOUT_MS)]
    assert PROXY_TIMEOUT_MS == 2000


@pytest.mark.parametrize(
    "connect",
    [
        lambda: None,
        lambda: FakeProxy(error=GLib.Error("io.github.wimm.Error.NotReady: Snapshot is not ready")),
        lambda: FakeProxy(error=GLib.Error("Timeout was reached")),
        lambda: FakeProxy(reply="not json"),
        lambda: FakeProxy(reply='{"schema": 1}'),
    ],
    ids=["absent", "not-ready", "timeout", "garbage", "old-schema"],
)
def test_unusable_instance_gives_none(connect: Callable[[], FakeProxy | None]) -> None:
    assert snapshot_from_instance(connect=connect) is None


def sources(*, instance: m.Snapshot | None, local: m.Snapshot | None) -> StatusSources:
    return StatusSources(from_instance=lambda: instance, sample_locally=lambda: local)


def test_status_prefers_the_running_instance(
    snapshot: m.Snapshot, capsys: pytest.CaptureFixture[str]
) -> None:
    other = replace(snapshot, pressure=m.Pressure.CRITICAL)
    assert run_status(arguments=["--json"], sources=sources(instance=snapshot, local=other)) == 0
    assert json.loads(capsys.readouterr().out)["pressure"] == "warning"


def test_status_samples_locally_without_an_instance(
    snapshot: m.Snapshot, capsys: pytest.CaptureFixture[str]
) -> None:
    code = run_status(arguments=["--json"], sources=sources(instance=None, local=snapshot))
    assert code == EXIT_OK
    assert json.loads(capsys.readouterr().out)["schema"] == m.SCHEMA_VERSION


def test_status_exits_3_when_there_is_no_state(capsys: pytest.CaptureFixture[str]) -> None:
    code = run_status(arguments=[], sources=sources(instance=None, local=None))
    captured = capsys.readouterr()
    assert code == EXIT_NO_STATE == 3
    assert captured.out == ""
    assert captured.err.strip()


def test_text_output_in_italian(snapshot: m.Snapshot, capsys: pytest.CaptureFixture[str]) -> None:
    run_status(arguments=[], sources=sources(instance=snapshot, local=None))
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("Memoria: ")
    assert "usati su" in lines[0]
    assert "Pressione: attenzione" in lines
    assert "Gruppi più grandi:" in lines
    assert any(line.strip().startswith("whitebox") for line in lines)
    assert any(line.startswith("Disco: 27,9 GB liberi su 375,8 GB") for line in lines)


def test_text_output_in_english(
    snapshot: m.Snapshot,
    capsys: pytest.CaptureFixture[str],
    english_catalog: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(name="LANGUAGE", value="en")
    run_status(arguments=[], sources=sources(instance=snapshot, local=None))
    out = capsys.readouterr().out
    assert "Memory: " in out
    assert "Pressure: warning" in out
    assert "Largest groups:" in out
    assert "Disk: 27.9 GB free of 375.8 GB" in out
    assert "Pressione" not in out


def test_text_lists_at_most_five_groups_largest_first(
    snapshot: m.Snapshot, capsys: pytest.CaptureFixture[str]
) -> None:
    base = snapshot.groups[0]
    groups = tuple(
        replace(
            base,
            id=m.GroupId(f"g_{index:06x}"),
            name=f"group-{index}",
            memory=m.MemoryUse(used=index * 1_000_000, reclaimable=0),
        )
        for index in range(1, 8)
    )
    run_status(arguments=[], sources=sources(instance=replace(snapshot, groups=groups), local=None))
    listed = [line.strip() for line in capsys.readouterr().out.splitlines() if "group-" in line]
    assert [line.split(":")[0] for line in listed] == [f"group-{n}" for n in (7, 6, 5, 4, 3)]


@pytest.mark.parametrize("flags", [[], ["--json"]])
def test_output_has_no_secrets_nor_control_characters(
    snapshot: m.Snapshot, capsys: pytest.CaptureFixture[str], flags: list[str]
) -> None:
    leaking = with_secret_cmdline(snapshot)
    group = replace(leaking.groups[0], name="evil\x1b[31m --token " + LEAKED_VALUE + "\nname")
    leaking = replace(leaking, groups=(group,))
    assert LEAKED_VALUE in snapshot_to_json(snapshot=leaking)
    run_status(arguments=flags, sources=sources(instance=None, local=leaking))
    out = capsys.readouterr().out
    assert out.strip()
    assert LEAKED_VALUE not in out
    if not flags:
        assert "\x1b" not in out
        assert all(ord(char) >= 32 or char == "\n" for char in out)
    else:
        assert "[REDACTED]" in redacted_snapshot_json(snapshot=leaking)
        assert "[REDACTED]" in out


def test_printable_drops_bidi_and_zero_width_characters() -> None:
    # U+202E reverses the rest of the line on the terminal; U+200B hides text inside a name.
    assert printable(text="safe\u202eexe.txt\u200b\u2066x") == "safe exe.txt x"


def test_redacted_json_masks_credentials_in_paths_and_reasons(snapshot: m.Snapshot) -> None:
    group = snapshot.groups[0]
    process = group.members[1]
    assert isinstance(process, m.ProcessMember)
    member = replace(process, cwd="/srv/https://u:" + LEAKED_VALUE + "@h/app")
    leaking = replace(snapshot, groups=(replace(group, members=(group.members[0], member)),))
    assert LEAKED_VALUE in snapshot_to_json(snapshot=leaking)

    assert LEAKED_VALUE not in redacted_snapshot_json(snapshot=leaking)
