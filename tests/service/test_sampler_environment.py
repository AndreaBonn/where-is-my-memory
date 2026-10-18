import logging
from pathlib import Path

import pytest

from wimm.service.sampler_environment import resolve_cache_table


def test_resolve_cache_table_logs_the_refused_caches_without_their_path(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    home = tmp_path / "home"
    secret = str(tmp_path / "outside-the-home" / "private-name")

    with caplog.at_level(logging.INFO, logger="wimm.service.sampler_environment"):
        table = resolve_cache_table(home=home, roots=(), environ={"GOCACHE": secret})

    assert [rejected.kind.value for rejected in table.rejected] == ["go_build"]
    assert "go_build" in caplog.text and "outside_home" in caplog.text
    assert "private-name" not in caplog.text


def test_resolve_cache_table_reads_the_process_environment_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("XDG_CACHE_HOME", str(home / "xdg"))

    table = resolve_cache_table(home=home, roots=())

    uv = next(cache for cache in table.caches if cache.kind.value == "uv")
    assert uv.path == home / "xdg" / "uv"
