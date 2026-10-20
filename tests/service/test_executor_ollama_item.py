"""T-6.38b: `ollama rm` of a system model, only while the system server answers (fakes only)."""

import os
from pathlib import Path

import psutil
import pytest

from tests.collectors.ollama_models_helpers import CURRENT_UID, TOOL, FakeProcess, FakeReader
from tests.service.executor_fakes import make_plan
from tests.service.fs_fakes import build_rig
from tests.service.ollama_item_fakes import (
    ENVIRON,
    MODEL_ID,
    NAME,
    NAME_SIZE,
    SPINNER,
    FakeOllama,
    ollama_rig,
    served_plan,
    served_step,
)
from wimm.collectors.ollama_command import OllamaCommandError, run_command
from wimm.core.constants import CACHE_COMMAND_TIMEOUT_S, OLLAMA_LIST_TIMEOUT_S
from wimm.model.actions import ItemFingerprint, PlanStep
from wimm.model.enums import ActionKind, Risk
from wimm.service.control_protocols import StepStatus
from wimm.service.errors import ControlFailed, ProtectedTarget, TargetChanged
from wimm.service.executor_ollama_item import NotSystemServed, check_ollama_item, run_ollama_item

OTHER_ID = "0123456789ab"
COMMAND_ENV = {"PATH": "/usr/bin", "LANG": "it_IT.UTF-8", "HOME": "/home/u"}


def test_the_model_is_removed_and_the_plan_reports_the_listed_size(tmp_path: Path) -> None:
    ollama = FakeOllama()
    rig = ollama_rig(home=tmp_path / "home", ollama=ollama)

    outcome = rig.executor().execute(plan=served_plan())[0]

    assert outcome.status is StepStatus.DONE
    assert outcome.freed_bytes == NAME_SIZE
    assert [call["argv"][1] for call in ollama.calls][-2:] == ["rm", "list"]
    assert NAME not in "\n".join(ollama.lines)


def test_rm_gets_the_exact_argv_the_list_environment_and_the_command_timeout(
    tmp_path: Path,
) -> None:
    ollama = FakeOllama()
    rig = ollama_rig(home=tmp_path / "home", ollama=ollama)

    run_ollama_item(step=served_step(), control=rig.control)

    (rm,) = ollama.rm_calls
    assert rm["argv"] == [TOOL, "rm", "--", NAME]
    assert rm["timeout_s"] == CACHE_COMMAND_TIMEOUT_S
    assert rm["env"] == COMMAND_ENV
    assert "SECRET" in ENVIRON
    listed = [call for call in ollama.calls if call["argv"][1] == "list"]
    assert {call["timeout_s"] for call in listed} == {OLLAMA_LIST_TIMEOUT_S}
    assert all(call["env"] == rm["env"] and call["argv"][0] == TOOL for call in listed)


@pytest.mark.parametrize(
    "reader",
    [
        FakeReader(),
        FakeReader(FakeProcess(uid=CURRENT_UID)),
        FakeReader(FakeProcess(uid=997), FakeProcess(uid=998, pid=2700)),
    ],
    ids=["no-server", "user-server", "two-servers"],
)
def test_without_the_system_server_nothing_is_run_at_check_or_at_run(
    tmp_path: Path, reader: FakeReader
) -> None:
    ollama = FakeOllama()
    rig = ollama_rig(home=tmp_path / "home", ollama=ollama, reader=reader)

    with pytest.raises(NotSystemServed):
        check_ollama_item(step=served_step(), control=rig.control)
    with pytest.raises(NotSystemServed):
        run_ollama_item(step=served_step(), control=rig.control)

    assert ollama.calls == []
    assert issubclass(NotSystemServed, ProtectedTarget)
    assert NotSystemServed().user_message


def test_a_remote_host_is_refused_but_the_same_setup_without_it_runs(tmp_path: Path) -> None:
    ollama = FakeOllama()
    remote = ollama_rig(
        home=tmp_path / "a", ollama=ollama, environ={**ENVIRON, "OLLAMA_HOST": "gpu.example:11434"}
    )
    local = ollama_rig(home=tmp_path / "b", ollama=ollama, environ={**ENVIRON})

    with pytest.raises(NotSystemServed):
        check_ollama_item(step=served_step(), control=remote.control)
    assert ollama.calls == []

    assert check_ollama_item(step=served_step(), control=local.control) is True


def test_a_changed_id_is_target_changed_and_never_reaches_rm(tmp_path: Path) -> None:
    ollama = FakeOllama()
    rig = ollama_rig(home=tmp_path / "home", ollama=ollama)

    with pytest.raises(TargetChanged):
        run_ollama_item(step=served_step(model_id=OTHER_ID), control=rig.control)
    with pytest.raises(TargetChanged):
        check_ollama_item(step=served_step(model_id=OTHER_ID), control=rig.control)

    assert ollama.rm_calls == []
    assert run_ollama_item(step=served_step(model_id=MODEL_ID), control=rig.control).status is (
        StepStatus.DONE
    )


def test_a_model_that_is_no_longer_listed_is_already_gone_and_nothing_is_run(
    tmp_path: Path,
) -> None:
    ollama = FakeOllama()
    rig = ollama_rig(home=tmp_path / "home", ollama=ollama)

    assert check_ollama_item(step=served_step(name="gone:1b"), control=rig.control) is False
    outcome = run_ollama_item(step=served_step(name="gone:1b"), control=rig.control)

    assert outcome.status is StepStatus.ALREADY_GONE
    assert ollama.rm_calls == []
    assert check_ollama_item(step=served_step(), control=rig.control) is True


@pytest.mark.parametrize("tool", [None, "ollama"], ids=["missing", "relative"])
def test_a_tool_without_an_absolute_path_is_refused_before_any_call(
    tmp_path: Path, tool: str | None
) -> None:
    ollama = FakeOllama()
    rig = ollama_rig(home=tmp_path / "home", ollama=ollama, tool=tool)

    with pytest.raises(ProtectedTarget):
        run_ollama_item(step=served_step(), control=rig.control)

    assert ollama.calls == []


def test_the_escapes_of_the_rm_spinner_never_reach_the_error(tmp_path: Path) -> None:
    ollama = FakeOllama(
        rm_returncode=1, rm_output=f"{SPINNER}Error: model '{NAME}' not found\x07\r\n"
    )
    rig = ollama_rig(home=tmp_path / "home", ollama=ollama)

    with pytest.raises(ControlFailed) as raised:
        run_ollama_item(step=served_step(), control=rig.control)

    message = raised.value.message
    assert "Error: model 'gemma3:4b' not found" in message
    assert "exited with code 1" in message
    assert not any(ord(char) < 32 or ord(char) == 127 for char in message)


def test_a_model_still_listed_after_rm_is_a_failure_not_a_success(tmp_path: Path) -> None:
    ollama = FakeOllama(rm_removes=False)
    rig = ollama_rig(home=tmp_path / "home", ollama=ollama)

    with pytest.raises(ControlFailed, match="still listed"):
        run_ollama_item(step=served_step(), control=rig.control)

    assert len(ollama.rm_calls) == 1


def test_a_failed_check_after_a_successful_rm_says_so(tmp_path: Path) -> None:
    ollama = FakeOllama(list_fails_after_rm=True)
    rig = ollama_rig(home=tmp_path / "home", ollama=ollama)

    with pytest.raises(ControlFailed, match="rm exited 0 but the check after it failed"):
        run_ollama_item(step=served_step(), control=rig.control)

    assert len(ollama.rm_calls) == 1


@pytest.mark.parametrize(
    "ollama",
    [
        FakeOllama(list_returncode=1),
        FakeOllama(list_error=OllamaCommandError("ollama did not finish within 10 s")),
        FakeOllama(lines=["NAME ID", "garbage"]),
    ],
    ids=["exit-code", "timeout", "unknown-format"],
)
def test_a_listing_that_cannot_be_trusted_stops_before_rm(
    tmp_path: Path, ollama: FakeOllama
) -> None:
    rig = ollama_rig(home=tmp_path / "home", ollama=ollama)

    with pytest.raises(ControlFailed):
        run_ollama_item(step=served_step(), control=rig.control)

    assert ollama.rm_calls == []


def test_a_rm_that_cannot_run_is_a_failure(tmp_path: Path) -> None:
    ollama = FakeOllama(rm_error=OllamaCommandError("ollama did not finish within 300 s"))
    rig = ollama_rig(home=tmp_path / "home", ollama=ollama)

    with pytest.raises(ControlFailed, match="did not finish"):
        run_ollama_item(step=served_step(), control=rig.control)


def test_the_real_seams_are_the_defaults_of_the_production_control(tmp_path: Path) -> None:
    control = build_rig(home=tmp_path / "home").control

    assert control.ollama_runner is run_command
    assert control.serve_reader is psutil
    assert control.environ is os.environ


def test_a_home_model_is_still_refused_and_the_ollama_commands_are_not_touched(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    manifest = home / ".ollama/models/manifests/registry/library/gemma3/4b"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{}", encoding="utf-8")
    ollama = FakeOllama()
    rig = ollama_rig(home=home, ollama=ollama)
    info = os.lstat(manifest)
    step = PlanStep(
        order=1,
        kind=ActionKind.CACHE_ITEM_REMOVE,
        target_label=NAME,
        fingerprint=ItemFingerprint(realpath=str(manifest), st_ino=info.st_ino, st_dev=info.st_dev),
        risk=Risk.DANGER,
    )

    with pytest.raises(ProtectedTarget):
        rig.executor().execute(plan=make_plan(steps=[step]))

    assert ollama.calls == []
    assert manifest.exists()
