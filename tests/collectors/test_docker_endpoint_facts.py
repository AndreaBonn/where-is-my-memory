import os
import socket
from pathlib import Path

import pytest

from wimm.collectors.docker_endpoint_facts import (
    MAX_DOCKER_FILE_BYTES,
    read_bounded_text,
    read_context_meta,
    read_docker_config,
    stat_path,
)
from wimm.core.docker_endpoint import EndpointSource, context_digest


def test_read_bounded_text_returns_regular_file_content(tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    target.write_text('{"currentContext": "x"}')
    assert read_bounded_text(path=target, limit=MAX_DOCKER_FILE_BYTES) == '{"currentContext": "x"}'


def test_read_bounded_text_refuses_oversized_file(tmp_path: Path) -> None:
    big = tmp_path / "big.json"
    big.write_text("x" * 11)
    assert read_bounded_text(path=big, limit=10) is None
    exact = tmp_path / "exact.json"
    exact.write_text("x" * 10)
    assert read_bounded_text(path=exact, limit=10) == "x" * 10


def test_read_bounded_text_does_not_follow_a_final_symlink(tmp_path: Path) -> None:
    real = tmp_path / "real.json"
    real.write_text("{}")
    link = tmp_path / "link.json"
    link.symlink_to(real)
    assert read_bounded_text(path=real, limit=10) == "{}"
    assert read_bounded_text(path=link, limit=10) is None


def test_read_bounded_text_refuses_non_regular_and_missing_and_binary(tmp_path: Path) -> None:
    assert read_bounded_text(path=tmp_path, limit=10) is None
    assert read_bounded_text(path=tmp_path / "missing", limit=10) is None
    binary = tmp_path / "bin"
    binary.write_bytes(b"\xff\xfe")
    assert read_bounded_text(path=binary, limit=10) is None


def test_read_docker_config_reads_dot_docker_config_json(tmp_path: Path) -> None:
    assert read_docker_config(home=tmp_path) is None
    (tmp_path / ".docker").mkdir()
    (tmp_path / ".docker/config.json").write_text('{"currentContext": "desktop-linux"}')
    assert read_docker_config(home=tmp_path) == '{"currentContext": "desktop-linux"}'


def test_read_context_meta_uses_the_digest_directory(tmp_path: Path) -> None:
    digest = context_digest("desktop-linux")
    meta_dir = tmp_path / ".docker/contexts/meta" / digest
    meta_dir.mkdir(parents=True)
    (meta_dir / "meta.json").write_text("{}")
    assert read_context_meta(home=tmp_path, digest=digest) == "{}"
    assert read_context_meta(home=tmp_path, digest=context_digest("other")) is None


def test_read_context_meta_refuses_a_non_digest_name(tmp_path: Path) -> None:
    (tmp_path / ".docker/contexts/meta").mkdir(parents=True)
    (tmp_path / "secret").mkdir()
    (tmp_path / "secret/meta.json").write_text("{}")
    assert read_context_meta(home=tmp_path, digest="../../../secret") is None


def test_stat_path_reports_socket_and_directory_facts(tmp_path: Path) -> None:
    runtime = tmp_path / "run"
    runtime.mkdir(mode=0o700)
    runtime.chmod(0o700)
    path = runtime / "s.sock"
    server = socket.socket(socket.AF_UNIX)
    try:
        server.bind(str(path))
        facts = stat_path(path=str(path))
        assert (facts.exists, facts.is_socket, facts.owned_by_user) == (True, True, True)
        assert facts.realpath == str(path.resolve())
        directory = stat_path(path=str(runtime))
        assert (directory.is_socket, directory.mode & 0o7777) == (False, 0o700)
        assert directory.owned_by_user is (os.getuid() == runtime.stat().st_uid)
    finally:
        server.close()


def test_stat_path_follows_a_symlink_to_report_the_real_target(tmp_path: Path) -> None:
    target = tmp_path / "real.sock"
    server = socket.socket(socket.AF_UNIX)
    try:
        server.bind(str(target))
        link = tmp_path / "link.sock"
        link.symlink_to(target)
        facts = stat_path(path=str(link))
        assert facts.is_socket
        assert facts.realpath == str(target.resolve())
    finally:
        server.close()


def test_stat_path_for_missing_path_and_regular_file(tmp_path: Path) -> None:
    missing = stat_path(path=str(tmp_path / "nope"))
    assert (missing.exists, missing.is_socket) == (False, False)
    regular = tmp_path / "f"
    regular.write_text("x")
    facts = stat_path(path=str(regular))
    assert (facts.exists, facts.is_socket) == (True, False)


def test_resolve_local_docker_endpoints_wires_config_meta_and_facts(tmp_path: Path) -> None:
    from wimm.collectors.docker_endpoint_facts import resolve_local_docker_endpoints

    runtime = tmp_path.resolve() / "run"
    runtime.mkdir(mode=0o700)
    runtime.chmod(0o700)
    path = runtime / "desktop.sock"
    home = tmp_path / "home"
    meta_dir = home / ".docker/contexts/meta" / context_digest("desktop-linux")
    meta_dir.mkdir(parents=True)
    (meta_dir / "meta.json").write_text(
        '{"Endpoints": {"docker": {"Host": "unix://' + str(path) + '"}}}'
    )
    (home / ".docker/config.json").write_text('{"currentContext": "desktop-linux"}')
    server = socket.socket(socket.AF_UNIX)
    try:
        server.bind(str(path))
        environ = {"XDG_RUNTIME_DIR": str(runtime)}
        resolution = resolve_local_docker_endpoints(environ=environ, home=home)
    finally:
        server.close()
    first = resolution.endpoints[0]
    assert (first.path, first.source) == (str(path), EndpointSource.CONFIG_CONTEXT)


def test_stat_path_for_a_path_that_cannot_be_stat_ed_is_present_but_trusted_for_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "docker.sock"
    target.write_text("x")
    original_stat = os.stat

    def deny(path: str, *args: object, **kwargs: object) -> os.stat_result:
        if path == str(target):
            raise PermissionError("denied")
        return original_stat(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(target=os, name="stat", value=deny)

    facts = stat_path(path=str(target))

    assert facts.exists is True
    assert (facts.is_socket, facts.owned_by_user, facts.mode) == (False, False, 0)
    assert facts.realpath == os.path.realpath(target)
