import logging
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from wimm.collectors.kernel_memory import (
    collect_kernel_memory,
    read_tmpfs_used_bytes,
    read_zram_bytes,
)
from wimm.model.raw import KernelMemory

FRSIZE = 4096


def make_zram(root: Path, name: str, mm_stat: str) -> None:
    (root / name).mkdir(parents=True)
    (root / name / "mm_stat").write_text(mm_stat)


def mount_line(*, mount_id: int, device: str, mountpoint: str, fstype: str) -> str:
    return f"{mount_id} 1 {device} / {mountpoint} rw,nosuid - {fstype} src rw\n"


def fake_statvfs(usage: dict[str, tuple[int, int]]) -> Callable[[str], SimpleNamespace]:
    def statvfs(path: str) -> SimpleNamespace:
        blocks, free = usage[path]
        return SimpleNamespace(f_blocks=blocks, f_bfree=free, f_frsize=FRSIZE)

    return statvfs


def test_read_zram_sums_mem_used_total_third_field_of_every_device(tmp_path: Path) -> None:
    make_zram(tmp_path, "zram0", "4096000 1000000 2000000 0 2500000 0 0 0\n")
    make_zram(tmp_path, "zram1", "  100   50   300 0 400 0 0 0\n")
    (tmp_path / "nvme0n1").mkdir()
    assert read_zram_bytes(sys_block=tmp_path) == 2_000_300


def test_read_zram_without_devices_or_sysfs_is_zero(tmp_path: Path) -> None:
    (tmp_path / "loop0").mkdir()
    assert read_zram_bytes(sys_block=tmp_path) == 0
    assert read_zram_bytes(sys_block=tmp_path / "missing") == 0


@pytest.mark.parametrize("content", ["", "1 2\n", "1 2 abc 0\n", "1 2 -5 0\n"])
def test_read_zram_unreadable_device_counts_zero_and_logs_debug(
    tmp_path: Path, content: str, caplog: pytest.LogCaptureFixture
) -> None:
    make_zram(tmp_path, "zram0", content)
    make_zram(tmp_path, "zram1", "1 1 700 0 0 0 0 0\n")
    with caplog.at_level(logging.DEBUG):
        assert read_zram_bytes(sys_block=tmp_path) == 700
    assert any(record.levelno == logging.DEBUG for record in caplog.records)


def test_read_zram_missing_mm_stat_counts_zero(tmp_path: Path) -> None:
    (tmp_path / "zram0").mkdir()
    assert read_zram_bytes(sys_block=tmp_path) == 0


def test_read_tmpfs_sums_used_bytes_of_tmpfs_mounts_only(tmp_path: Path) -> None:
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        mount_line(mount_id=1, device="0:20", mountpoint="/run", fstype="tmpfs")
        + mount_line(mount_id=2, device="0:21", mountpoint="/mnt/ramdisk", fstype="tmpfs")
        + mount_line(mount_id=3, device="259:1", mountpoint="/", fstype="ext4")
        + mount_line(mount_id=4, device="0:50", mountpoint="/mnt/nas", fstype="nfs4")
        + mount_line(mount_id=5, device="0:51", mountpoint="/proc", fstype="proc")
    )
    usage = {"/run": (1000, 400), "/mnt/ramdisk": (500, 500)}
    total = read_tmpfs_used_bytes(mountinfo=mountinfo, statvfs=fake_statvfs(usage))
    assert total == (600 + 0) * FRSIZE


def test_read_tmpfs_counts_bind_mounts_of_the_same_filesystem_once(tmp_path: Path) -> None:
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        mount_line(mount_id=1, device="0:20", mountpoint="/run", fstype="tmpfs")
        + mount_line(mount_id=2, device="0:20", mountpoint="/var/run", fstype="tmpfs")
    )
    usage = {"/run": (100, 90), "/var/run": (100, 90)}
    assert read_tmpfs_used_bytes(mountinfo=mountinfo, statvfs=fake_statvfs(usage)) == 10 * FRSIZE


def test_read_tmpfs_decodes_octal_escapes_in_mount_points(tmp_path: Path) -> None:
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        mount_line(mount_id=1, device="0:20", mountpoint="/mnt/my\\040disk", fstype="tmpfs")
    )
    usage = {"/mnt/my disk": (10, 4)}
    assert read_tmpfs_used_bytes(mountinfo=mountinfo, statvfs=fake_statvfs(usage)) == 6 * FRSIZE


def test_read_tmpfs_statvfs_error_counts_zero_for_that_mount_only(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        mount_line(mount_id=1, device="0:20", mountpoint="/gone", fstype="tmpfs")
        + mount_line(mount_id=2, device="0:21", mountpoint="/run", fstype="tmpfs")
    )
    good = fake_statvfs({"/run": (10, 5)})

    def statvfs(path: str) -> SimpleNamespace:
        if path == "/gone":
            raise PermissionError(path)
        return good(path)

    with caplog.at_level(logging.DEBUG):
        assert read_tmpfs_used_bytes(mountinfo=mountinfo, statvfs=statvfs) == 5 * FRSIZE
    assert "/gone" in caplog.text


def test_read_tmpfs_unreadable_mountinfo_and_garbage_lines_are_zero(tmp_path: Path) -> None:
    statvfs = fake_statvfs({})
    assert read_tmpfs_used_bytes(mountinfo=tmp_path / "missing", statvfs=statvfs) == 0
    garbage = tmp_path / "mountinfo"
    garbage.write_text("nonsense\n\n1 2 3 - tmpfs\n")
    assert read_tmpfs_used_bytes(mountinfo=garbage, statvfs=statvfs) == 0


def test_collect_kernel_memory_combines_both_readers_and_never_raises(tmp_path: Path) -> None:
    make_zram(tmp_path, "zram0", "1 1 900 0 0 0 0 0\n")
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(mount_line(mount_id=1, device="0:20", mountpoint="/run", fstype="tmpfs"))
    result = collect_kernel_memory(
        sys_block=tmp_path, mountinfo=mountinfo, statvfs=fake_statvfs({"/run": (8, 2)})
    )
    assert result == KernelMemory(zram=900, tmpfs_used=6 * FRSIZE)
    empty = collect_kernel_memory(sys_block=tmp_path / "x", mountinfo=tmp_path / "y")
    assert empty == KernelMemory(zram=0, tmpfs_used=0)


def test_read_tmpfs_falls_back_to_a_bind_mount_when_the_first_is_unreachable(
    tmp_path: Path,
) -> None:
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        mount_line(mount_id=1, device="0:20", mountpoint="/hidden", fstype="tmpfs")
        + mount_line(mount_id=2, device="0:20", mountpoint="/run", fstype="tmpfs")
    )
    good = fake_statvfs({"/run": (100, 90)})

    def statvfs(path: str) -> SimpleNamespace:
        if path == "/hidden":
            raise PermissionError(path)
        return good(path)

    assert read_tmpfs_used_bytes(mountinfo=mountinfo, statvfs=statvfs) == 10 * FRSIZE
