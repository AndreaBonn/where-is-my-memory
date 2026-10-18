"""R24: the ollama models are not cleaned while `ollama serve` is alive (tmpdir only)."""

from collections.abc import Sequence
from pathlib import Path

import pytest

from tests.service.fs_fakes import FsRig, build_rig, dir_plan, make_cache
from wimm.model.enums import ActionKind
from wimm.service.control_protocols import StepStatus
from wimm.service.errors import ProtectedTarget

CLEAN = ActionKind.CACHE_CLEAN
SERVE = ("ollama", ["/usr/local/bin/ollama", "serve"])


def make_models(*, home: Path) -> Path:
    """An ollama models folder: a blob and a manifest, the only two folders that are emptied."""
    models = home / ".ollama/models"
    (models / "blobs").mkdir(parents=True)
    (models / "manifests").mkdir()
    (models / "blobs" / "sha256-aa").write_bytes(b"a" * 4096)
    (models / "manifests" / "latest").write_text("{}", encoding="utf-8")
    return models


def rig_with(*, tmp_path: Path, processes: Sequence[tuple[str, list[str]]]) -> FsRig:
    return build_rig(home=tmp_path / "home", processes=processes)


def test_ollama_clean_is_refused_while_serve_is_alive_and_nothing_is_touched(
    tmp_path: Path,
) -> None:
    rig = rig_with(tmp_path=tmp_path, processes=[("bash", ["bash"]), SERVE])
    folder = make_models(home=rig.home)

    with pytest.raises(ProtectedTarget) as raised:
        rig.executor().execute(plan=dir_plan(kind=CLEAN, path=folder))

    assert raised.value.user_message == "Chiudi ollama (ollama serve) prima di cancellare i modelli"
    assert (folder / "blobs" / "sha256-aa").exists()
    assert (folder / "manifests" / "latest").exists()


def test_ollama_clean_runs_when_no_process_serves(tmp_path: Path) -> None:
    rig = rig_with(tmp_path=tmp_path, processes=[("bash", ["bash"])])
    folder = make_models(home=rig.home)

    outcome = rig.executor().execute(plan=dir_plan(kind=CLEAN, path=folder))[0]

    assert outcome.status is StepStatus.DONE
    assert not (folder / "blobs" / "sha256-aa").exists()


@pytest.mark.parametrize("argv", [["ollama", "run", "llama3"], ["ollama", "list"]])
def test_ollama_run_and_list_do_not_block_the_clean(tmp_path: Path, argv: list[str]) -> None:
    rig = rig_with(tmp_path=tmp_path, processes=[("ollama", argv)])
    folder = make_models(home=rig.home)

    outcome = rig.executor().execute(plan=dir_plan(kind=CLEAN, path=folder))[0]

    assert outcome.status is StepStatus.DONE


def test_a_live_ollama_does_not_influence_other_caches(tmp_path: Path) -> None:
    rig = rig_with(tmp_path=tmp_path, processes=[SERVE])
    folder = make_cache(home=rig.home, relative=".cache/pip")

    outcome = rig.executor().execute(plan=dir_plan(kind=CLEAN, path=folder))[0]

    assert outcome.status is StepStatus.DONE
