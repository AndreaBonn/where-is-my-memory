"""L5 review: what the client reaches is judged from wimm's OLLAMA_HOST and every ollama process."""

from pathlib import Path

import pytest

from tests.collectors.ollama_models_helpers import SERVICE_UID, FakeProcess, FakeReader
from tests.service.ollama_home_fakes import ManifestOllama, home_rig, item_plan, item_step
from tests.service.ollama_item_fakes import ENVIRON, NAME, FakeOllama, ollama_rig, served_plan
from wimm.service.control_protocols import StepStatus
from wimm.service.errors import ControlFailed, ProtectedTarget, TargetChanged
from wimm.service.executor_cache_item import run_cache_item
from wimm.service.executor_ollama_item import NotSystemServed, check_ollama_item, run_ollama_item

UNREADABLE = FakeProcess(uid=SERVICE_UID, cmdline=None, pid=77)


def test_an_unreadable_ollama_process_beside_the_system_server_refuses(tmp_path: Path) -> None:
    ollama = FakeOllama()
    reader = FakeReader(FakeProcess(uid=SERVICE_UID), UNREADABLE)
    rig = ollama_rig(home=tmp_path / "home", ollama=ollama, reader=reader)

    with pytest.raises(NotSystemServed):
        run_ollama_item(step=served_plan().steps[0], control=rig.control)

    assert ollama.calls == []


def test_a_client_port_other_than_the_default_refuses_the_system_server(tmp_path: Path) -> None:
    ollama = FakeOllama()
    environ = {**ENVIRON, "OLLAMA_HOST": "127.0.0.1:8080"}
    rig = ollama_rig(home=tmp_path / "home", ollama=ollama, environ=environ)

    with pytest.raises(NotSystemServed):
        check_ollama_item(step=served_plan().steps[0], control=rig.control)

    assert ollama.calls == []


def test_a_client_host_with_userinfo_refuses_the_system_server(tmp_path: Path) -> None:
    environ = {**ENVIRON, "OLLAMA_HOST": "me:pw@127.0.0.1:11434"}
    rig = ollama_rig(home=tmp_path / "home", ollama=FakeOllama(), environ=environ)

    with pytest.raises(ProtectedTarget):
        check_ollama_item(step=served_plan().steps[0], control=rig.control)


def test_the_default_port_written_out_still_reaches_the_system_server(tmp_path: Path) -> None:
    environ = {**ENVIRON, "OLLAMA_HOST": "127.0.0.1:11434"}
    rig = ollama_rig(home=tmp_path / "home", ollama=FakeOllama(), environ=environ)

    assert check_ollama_item(step=served_plan().steps[0], control=rig.control) is True


def test_a_home_rm_needs_exactly_one_listed_row_with_the_exact_name(tmp_path: Path) -> None:
    ollama = ManifestOllama()
    rig, manifest = home_rig(home=tmp_path / "home", ollama=ollama)

    outcome = rig.executor().execute(plan=item_plan(manifest=manifest))[0]

    assert outcome.status is StepStatus.DONE
    assert [call["argv"][1] for call in ollama.calls] == ["list", "rm"]


def test_a_home_rm_is_refused_when_the_name_is_not_listed(tmp_path: Path) -> None:
    others = [line for line in ManifestOllama().lines if not line.startswith(f"{NAME} ")]
    ollama = ManifestOllama(lines=others)
    rig, manifest = home_rig(home=tmp_path / "home", ollama=ollama)

    with pytest.raises(TargetChanged):
        run_cache_item(step=item_step(manifest=manifest), control=rig.control)

    assert ollama.rm_calls == []
    assert manifest.exists()


def test_a_home_rm_is_refused_when_the_name_is_listed_twice_is_an_unknown_listing(
    tmp_path: Path,
) -> None:
    base = ManifestOllama().lines
    row = next(line for line in base if line.startswith(f"{NAME} "))
    ollama = ManifestOllama(lines=[base[0], row, *base[1:]])
    rig, manifest = home_rig(home=tmp_path / "home", ollama=ollama)

    with pytest.raises(ControlFailed):
        run_cache_item(step=item_step(manifest=manifest), control=rig.control)

    assert ollama.rm_calls == []
