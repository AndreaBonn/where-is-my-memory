"""T-6.38c: `ollama rm` of a home model, only while the user's own server serves the home store."""

import os
from dataclasses import replace
from pathlib import Path

import pytest

from tests.collectors.ollama_models_helpers import (
    CURRENT_UID,
    SERVICE_UID,
    TOOL,
    FakeProcess,
    FakeReader,
)
from tests.service.ollama_home_fakes import (
    ManifestOllama,
    blobs_disk_bytes,
    home_rig,
    item_plan,
    item_step,
    write_manifest,
)
from tests.service.ollama_item_fakes import ENVIRON, NAME
from wimm.core.constants import CACHE_COMMAND_TIMEOUT_S
from wimm.service.control_protocols import StepStatus
from wimm.service.errors import ControlFailed, ProtectedTarget, TargetChanged
from wimm.service.executor_cache_item import check_cache_item, run_cache_item
from wimm.service.executor_ollama_home import (
    ServerIsSystem,
    ServerNotRunning,
    ServersAmbiguous,
    ServerUsesOtherStore,
)

COMMAND_ENV = {"PATH": "/usr/bin", "LANG": "it_IT.UTF-8", "HOME": "/home/u"}
STRANGER_UID = 4242


def test_the_model_is_removed_while_the_home_server_runs(tmp_path: Path) -> None:
    ollama = ManifestOllama()
    rig, manifest = home_rig(home=tmp_path / "home", ollama=ollama)

    outcome = rig.executor().execute(plan=item_plan(manifest=manifest))[0]

    assert outcome.status is StepStatus.DONE
    assert outcome.freed_bytes == blobs_disk_bytes(store=tmp_path / "home/.ollama/models")
    assert not manifest.exists()
    (rm,) = ollama.calls
    assert rm["argv"] == [TOOL, "rm", "--", NAME]
    assert rm["timeout_s"] == CACHE_COMMAND_TIMEOUT_S
    assert rm["env"] == COMMAND_ENV
    assert "SECRET" in ENVIRON


@pytest.mark.parametrize(
    ("reader", "error"),
    [
        (FakeReader(), ServerNotRunning),
        (
            FakeReader(
                FakeProcess(uid=CURRENT_UID, environ_value={"OLLAMA_MODELS": "/srv/models"})
            ),
            ServerUsesOtherStore,
        ),
        (FakeReader(FakeProcess(uid=SERVICE_UID)), ServerIsSystem),
        (
            FakeReader(FakeProcess(uid=CURRENT_UID), FakeProcess(uid=SERVICE_UID, pid=9)),
            ServersAmbiguous,
        ),
    ],
    ids=["S0-no-server", "S1prime-other-store", "S2-system-server", "S3-two-servers"],
)
def test_any_situation_but_the_home_server_refuses_at_check_and_at_run(
    tmp_path: Path, reader: FakeReader, error: type[ProtectedTarget]
) -> None:
    ollama = ManifestOllama()
    rig, manifest = home_rig(home=tmp_path / "home", ollama=ollama, reader=reader)
    step = item_step(manifest=manifest)

    with pytest.raises(error):
        check_cache_item(step=step, control=rig.control)
    with pytest.raises(error):
        run_cache_item(step=step, control=rig.control)

    assert ollama.calls == []
    assert manifest.exists()


def test_a_remote_host_is_ambiguous_and_the_same_setup_without_it_runs(tmp_path: Path) -> None:
    ollama = ManifestOllama()
    rig, manifest = home_rig(home=tmp_path / "home", ollama=ollama)
    remote = replace(rig.control, environ={**ENVIRON, "OLLAMA_HOST": "10.0.0.5:11434"})

    with pytest.raises(ServersAmbiguous):
        run_cache_item(step=item_step(manifest=manifest), control=remote)
    assert ollama.calls == []

    done = run_cache_item(step=item_step(manifest=manifest), control=rig.control)
    assert done.status is StepStatus.DONE


def test_a_symlinked_manifest_is_refused_but_the_real_file_is_removed(tmp_path: Path) -> None:
    ollama = ManifestOllama()
    rig, manifest = home_rig(home=tmp_path / "home", ollama=ollama)
    step = item_step(manifest=manifest)
    real = manifest.with_name("real")
    manifest.rename(real)
    manifest.symlink_to(real)

    with pytest.raises(TargetChanged):
        run_cache_item(step=step, control=rig.control)
    assert ollama.calls == []

    manifest.unlink()
    real.rename(manifest)
    ollama.manifest = manifest
    assert run_cache_item(step=item_step(manifest=manifest), control=rig.control).status is (
        StepStatus.DONE
    )


def test_a_symlink_in_the_path_is_refused(tmp_path: Path) -> None:
    ollama = ManifestOllama()
    rig, manifest = home_rig(home=tmp_path / "home", ollama=ollama)
    step = item_step(manifest=manifest)
    folder = manifest.parent
    folder.rename(folder.with_name("moved"))
    folder.symlink_to(folder.with_name("moved"))

    with pytest.raises(TargetChanged):
        run_cache_item(step=step, control=rig.control)

    assert ollama.calls == []


@pytest.mark.parametrize(("ino_shift", "dev_shift"), [(1, 0), (0, 1)], ids=["inode", "device"])
def test_another_file_than_planned_is_refused(
    tmp_path: Path, ino_shift: int, dev_shift: int
) -> None:
    ollama = ManifestOllama()
    rig, manifest = home_rig(home=tmp_path / "home", ollama=ollama)

    step = item_step(manifest=manifest, ino_shift=ino_shift, dev_shift=dev_shift)
    with pytest.raises(TargetChanged):
        run_cache_item(step=step, control=rig.control)

    assert ollama.calls == []
    assert manifest.exists()


def test_a_manifest_of_another_owner_is_refused(tmp_path: Path) -> None:
    ollama = ManifestOllama()
    rig, manifest = home_rig(home=tmp_path / "home", ollama=ollama)
    stranger = replace(rig.control, owner_of=lambda path: STRANGER_UID)

    with pytest.raises(ProtectedTarget, match="owned"):
        run_cache_item(step=item_step(manifest=manifest), control=stranger)

    assert ollama.calls == []
    assert run_cache_item(step=item_step(manifest=manifest), control=rig.control).status is (
        StepStatus.DONE
    )


def test_a_manifest_the_rule_no_longer_recognises_is_refused(tmp_path: Path) -> None:
    ollama = ManifestOllama()
    rig, manifest = home_rig(home=tmp_path / "home", ollama=ollama)
    step = item_step(manifest=manifest)
    manifest.write_text("{}", encoding="utf-8")

    with pytest.raises(ProtectedTarget, match="recognised"):
        run_cache_item(step=step, control=rig.control)

    assert ollama.calls == []


@pytest.mark.parametrize(
    "relative",
    [
        "blobs/sha256-" + "a" * 64,
        "manifests/registry.ollama.ai/library/gemma3",
        "manifests/registry.ollama.ai/library/-rf/4b",
    ],
    ids=["a-blob", "wrong-depth", "invalid-name"],
)
def test_only_a_manifest_with_a_valid_name_goes_to_rm(tmp_path: Path, relative: str) -> None:
    ollama = ManifestOllama()
    rig, _ = home_rig(home=tmp_path / "home", ollama=ollama)
    store = tmp_path / "home/.ollama/models"
    target = store / relative
    if not target.exists():
        write_manifest(store=store, relative=relative)

    with pytest.raises(ProtectedTarget):
        run_cache_item(step=item_step(manifest=target), control=rig.control)

    assert ollama.calls == []


def test_a_manifest_that_is_gone_is_already_gone_and_nothing_is_run(tmp_path: Path) -> None:
    ollama = ManifestOllama()
    rig, manifest = home_rig(home=tmp_path / "home", ollama=ollama)
    step = item_step(manifest=manifest)
    manifest.unlink()

    assert check_cache_item(step=step, control=rig.control) is False
    assert run_cache_item(step=step, control=rig.control).status is StepStatus.ALREADY_GONE
    assert ollama.calls == []


def test_a_manifest_still_there_after_rm_is_a_failure_and_no_file_is_deleted(
    tmp_path: Path,
) -> None:
    ollama = ManifestOllama(rm_removes=False)
    rig, manifest = home_rig(home=tmp_path / "home", ollama=ollama)

    with pytest.raises(ControlFailed, match="still"):
        run_cache_item(step=item_step(manifest=manifest), control=rig.control)

    assert manifest.exists()
    assert len(ollama.rm_calls) == 1
    assert len(os.listdir(tmp_path / "home/.ollama/models/blobs")) == 2


def test_a_rm_with_an_error_code_is_a_failure(tmp_path: Path) -> None:
    ollama = ManifestOllama(rm_returncode=1, rm_output="Error: nope")
    rig, manifest = home_rig(home=tmp_path / "home", ollama=ollama)

    with pytest.raises(ControlFailed, match="code 1"):
        run_cache_item(step=item_step(manifest=manifest), control=rig.control)

    assert manifest.exists()
