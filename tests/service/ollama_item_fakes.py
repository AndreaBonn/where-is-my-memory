"""A control wired to a fake system ollama: no real command, no real process (T-6.38b)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from tests.collectors.ollama_models_helpers import (
    CURRENT_UID,
    SERVICE_UID,
    TOOL,
    FakeProcess,
    FakeReader,
    listing,
)
from tests.service.executor_fakes import make_plan
from tests.service.fs_fakes import FsRig, build_rig
from wimm.collectors.ollama_command import CommandOutput, OllamaCommandError
from wimm.model.actions import Plan, PlanStep
from wimm.model.enums import ActionKind, Risk
from wimm.model.served_fingerprint import ServedModelFingerprint

NAME = "gemma3:4b"
MODEL_ID = "a2af6cc3eb7f"
NAME_SIZE = 3_300_000_000
SPINNER = "\x1b[?25l\x1b[?2026h\x1b[1G⠋ \x1b[K\x1b[?25h\x1b[2K\x1b[1G"
ENVIRON = {"PATH": "/usr/bin", "LANG": "it_IT.UTF-8", "HOME": "/home/u", "SECRET": "x"}


@dataclass
class FakeOllama:
    """Answers `list` from the real 0.18.0 output and `rm` by dropping the row (or not)."""

    rm_returncode: int = 0
    rm_output: str = ""
    rm_removes: bool = True
    list_returncode: int = 0
    list_error: OllamaCommandError | None = None
    rm_error: OllamaCommandError | None = None
    # The server stops answering right after a successful rm: the check that follows fails.
    list_fails_after_rm: bool = False
    calls: list[dict[str, Any]] = field(default_factory=list)
    lines: list[str] = field(default_factory=lambda: listing().split("\n"))

    def __call__(
        self, *, argv: Sequence[str], timeout_s: float, env: Mapping[str, str]
    ) -> CommandOutput:
        self.calls.append({"argv": list(argv), "timeout_s": timeout_s, "env": dict(env)})
        if argv[1] == "rm":
            return self._rm(argv=argv)
        if self.list_error is not None:
            raise self.list_error
        if self.list_returncode:
            return CommandOutput(returncode=self.list_returncode, stdout="", stderr="Error: down")
        return CommandOutput(returncode=0, stdout="\n".join(self.lines), stderr="")

    def _rm(self, *, argv: Sequence[str]) -> CommandOutput:
        if self.rm_error is not None:
            raise self.rm_error
        if self.rm_removes and not self.rm_returncode:
            self.lines = [line for line in self.lines if line.split()[:1] != [argv[-1]]]
        if self.list_fails_after_rm:
            self.list_returncode = 1
        return CommandOutput(returncode=self.rm_returncode, stdout=self.rm_output, stderr="")

    @property
    def rm_calls(self) -> list[dict[str, Any]]:
        return [call for call in self.calls if call["argv"][1] == "rm"]


def system_server() -> FakeReader:
    return FakeReader(FakeProcess(uid=SERVICE_UID))


def ollama_rig(
    *,
    home: Path,
    ollama: FakeOllama,
    reader: FakeReader | None = None,
    tool: str | None = TOOL,
    environ: Mapping[str, str] | None = None,
) -> FsRig:
    """The folder-action rig with the ollama seams replaced by fakes."""
    rig = build_rig(home=home)
    rig.control = replace(
        rig.control,
        which=lambda name: tool,
        ollama_runner=ollama,
        serve_reader=reader or system_server(),
        environ=ENVIRON if environ is None else environ,
        uid=CURRENT_UID,
    )
    return rig


def served_step(*, name: str = NAME, model_id: str = MODEL_ID) -> PlanStep:
    return PlanStep(
        order=1,
        kind=ActionKind.CACHE_ITEM_REMOVE,
        target_label=name,
        fingerprint=ServedModelFingerprint(name=name, model_id=model_id),
        risk=Risk.DANGER,
    )


def served_plan(*, name: str = NAME, model_id: str = MODEL_ID) -> Plan:
    return make_plan(steps=[served_step(name=name, model_id=model_id)])
