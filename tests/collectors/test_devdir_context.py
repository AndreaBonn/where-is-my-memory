import os
from pathlib import Path
from typing import Any

import pytest

from tests.helpers import FailingHandle
from wimm.collectors.devdir_context import read_devdir_context


def test_gitignore_read_failure_gives_an_empty_text_not_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "node_modules").mkdir()
    (project / ".gitignore").write_text("node_modules/\n", encoding="utf-8")

    healthy = read_devdir_context(path=project / "node_modules", home=tmp_path)

    def failing_fdopen(descriptor: int, mode: str) -> Any:
        return FailingHandle(descriptor)

    monkeypatch.setattr(target=os, name="fdopen", value=failing_fdopen)
    failing = read_devdir_context(path=project / "node_modules", home=tmp_path)

    assert healthy.gitignore_text == "node_modules/\n"
    assert failing.gitignore_text == ""
    assert failing.parent_entries == healthy.parent_entries
