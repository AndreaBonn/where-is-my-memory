import re
import selectors
import subprocess
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest

from wimm.collectors.sockets import (
    collect_sockets,
    connections_for_server,
    listening_ports_by_pid,
    non_listening_by_pid,
    non_listening_for_ports,
)
from wimm.model.raw import RawSocket

PORT = 8123
SERVER_TIMEOUT = 10
PROCESS_TIMEOUT = 5
REQUEST_TIMEOUT = 5
SERVER = RawSocket(pid=10, laddr=("127.0.0.1", PORT), raddr=None, status="LISTEN")
WORKER = RawSocket(
    pid=11, laddr=("127.0.0.1", PORT), raddr=("127.0.0.1", 40000), status="ESTABLISHED"
)
CLIENT = RawSocket(
    pid=12, laddr=("127.0.0.1", 40000), raddr=("127.0.0.1", PORT), status="ESTABLISHED"
)
UNRELATED = RawSocket(
    pid=30, laddr=("192.0.2.1", 40000), raddr=("192.0.2.2", PORT), status="ESTABLISHED"
)


def test_socket_helpers() -> None:
    sockets = (
        SERVER,
        WORKER,
        CLIENT,
        UNRELATED,
        RawSocket(pid=None, laddr=None, raddr=None, status="CLOSE"),
    )
    assert listening_ports_by_pid(sockets=sockets) == {10: frozenset({PORT})}
    assert non_listening_by_pid(sockets=sockets)[11] == frozenset(
        {("127.0.0.1", PORT, "127.0.0.1", 40000)}
    )
    assert connections_for_server(sockets=sockets, pid=11, ppid={11: 10, 12: 10}) == (
        WORKER,
        CLIENT,
    )
    assert connections_for_server(sockets=sockets, pid=10, ppid={11: 10, 12: 10}) == (
        WORKER,
        CLIENT,
    )
    assert connections_for_server(sockets=sockets, pid=30, ppid={}) == ()
    assert listening_ports_by_pid(sockets=()) == {}
    assert non_listening_by_pid(sockets=()) == {}


def test_socket_helpers_cycles_and_incomplete_addresses() -> None:
    sockets = (SERVER, WORKER, RawSocket(pid=11, laddr=None, raddr=None, status="CLOSE"))
    assert connections_for_server(sockets=sockets, pid=11, ppid={11: 10, 10: 11}) == (WORKER,)
    assert non_listening_by_pid(sockets=sockets) == {
        11: frozenset({("127.0.0.1", PORT, "127.0.0.1", 40000)})
    }


def test_collect_sockets_fake() -> None:
    def source(*, kind: str) -> list[SimpleNamespace]:
        assert kind == "tcp"
        return [SimpleNamespace(pid=10, laddr=("127.0.0.1", PORT), raddr=(), status="LISTEN")]

    result = collect_sockets(source=source)
    assert result.data == (SERVER,)
    assert result.error is None


@pytest.mark.parametrize(
    "error",
    [
        psutil.AccessDenied(pid=1),
        psutil.NoSuchProcess(pid=1),
        psutil.ZombieProcess(pid=1),
        OSError("failed"),
    ],
)
def test_collect_sockets_failure(error: Exception, caplog: pytest.LogCaptureFixture) -> None:
    def source(*, kind: str) -> list[SimpleNamespace]:
        raise error

    result = collect_sockets(source=source)
    assert result.data == () and result.error
    assert "WARNING" in caplog.text


@pytest.mark.integration
def test_real_http_server_listening_and_new_connection(tmp_path: Path) -> None:
    process = subprocess.Popen(
        args=["/usr/bin/python3", "-u", "-m", "http.server", "0", "--bind", "127.0.0.1"],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        port = read_server_port(process=process)
        result = collect_sockets()
        assert result.error is None
        assert port in listening_ports_by_pid(sockets=result.data)[process.pid]
        assert_http_connection(port=port, before=result.data)
    finally:
        stop_server(process=process)


def read_server_port(process: subprocess.Popen[str]) -> int:
    assert process.stdout is not None
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        assert selector.select(timeout=SERVER_TIMEOUT), "HTTP server did not start"
        line = process.stdout.readline()
    match = re.search(r"port (\d+)", line)
    if match is None:
        output, _ = process.communicate(timeout=PROCESS_TIMEOUT)
        pytest.fail(reason=line + output)
    return int(match[1])


def assert_http_connection(port: int, before: tuple[RawSocket, ...]) -> None:
    ports = frozenset({port})
    previous = non_listening_for_ports(sockets=before, ports=ports)
    with urllib.request.urlopen(
        url=f"http://127.0.0.1:{port}", timeout=REQUEST_TIMEOUT
    ) as response:
        assert response.status == 200
        response.read()
    after = collect_sockets()
    assert after.error is None
    assert non_listening_for_ports(sockets=after.data, ports=ports) - previous


def stop_server(process: subprocess.Popen[str]) -> None:
    try:
        process.terminate()
        try:
            process.wait(timeout=PROCESS_TIMEOUT)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=PROCESS_TIMEOUT)
    finally:
        if process.stdout is not None:
            process.stdout.close()


def test_local_client_on_non_loopback_interface() -> None:
    server = RawSocket(pid=10, laddr=("192.0.2.1", PORT), raddr=None, status="LISTEN")
    client = RawSocket(
        pid=20, laddr=("192.0.2.1", 40000), raddr=("192.0.2.1", PORT), status="ESTABLISHED"
    )
    assert connections_for_server(sockets=(server, client), pid=10, ppid={}) == (client,)


@pytest.mark.parametrize("status", ["ESTABLISHED", "TIME_WAIT", "CLOSE_WAIT", "FIN_WAIT1"])
def test_server_connections_include_unowned_closed_traffic(status: str) -> None:
    closed = RawSocket(pid=None, laddr=WORKER.laddr, raddr=WORKER.raddr, status=status)
    other = RawSocket(pid=None, laddr=("127.0.0.1", PORT + 1), raddr=WORKER.raddr, status=status)
    sockets = (SERVER, closed, other)
    assert connections_for_server(sockets=sockets, pid=11, ppid={11: 10}) == (closed,)
    assert non_listening_for_ports(sockets=sockets, ports=frozenset({PORT})) == frozenset(
        {("127.0.0.1", PORT, "127.0.0.1", 40000)}
    )
    assert non_listening_for_ports(sockets=sockets, ports=frozenset()) == frozenset()


@pytest.mark.parametrize("address", ["::1", "::ffff:127.0.0.1"])
def test_ipv6_loopback_client_matches_server(address: str) -> None:
    client = RawSocket(pid=None, laddr=("::", 40000), raddr=(address, PORT), status="TIME_WAIT")
    assert connections_for_server(sockets=(SERVER, client), pid=10, ppid={}) == (client,)
    assert non_listening_for_ports(sockets=(SERVER, client), ports=frozenset({PORT})) == (
        frozenset({("::", 40000, address, PORT)})
    )


def test_mapped_local_interface_client_matches_server() -> None:
    server = RawSocket(pid=10, laddr=("192.0.2.1", PORT), raddr=None, status="LISTEN")
    client = RawSocket(
        pid=20, laddr=("::", 40000), raddr=("::ffff:192.0.2.1", PORT), status="TIME_WAIT"
    )
    assert connections_for_server(sockets=(server, client), pid=10, ppid={}) == (client,)
