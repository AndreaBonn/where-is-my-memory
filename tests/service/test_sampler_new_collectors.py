import logging
from dataclasses import replace
from pathlib import Path
from typing import NoReturn

import pytest

from tests.service.sampler_helpers import make_sampler
from wimm.model.enums import GpuVendor, Pressure
from wimm.model.memory import GpuMemory
from wimm.model.raw import KernelMemory, PsiSample
from wimm.service.sampler import Sampler
from wimm.service.sampler_collectors import safe_read

VIDEO = (GpuMemory(vendor=GpuVendor.NVIDIA, used_bytes=300, total_bytes=1000),)
KERNEL = KernelMemory(zram=50, tmpfs_used=20)
SEVERE_PSI = PsiSample(some_avg60=40.0, full_avg60=9.0)


def _boom() -> NoReturn:
    raise OSError("collector failed")


def test_cycle_fills_video_kernel_voices_and_psi_from_the_new_collectors(tmp_path: Path) -> None:
    sampler = make_sampler(tmp_path=tmp_path)
    sampler.collectors = replace(
        sampler.collectors,
        kernel_memory=lambda: KERNEL,
        video=lambda: VIDEO,
        psi=lambda: SEVERE_PSI,
    )

    snapshot = sampler.run_cycle()

    assert snapshot.memory.video == VIDEO
    assert snapshot.memory.breakdown.zram == 50
    assert snapshot.memory.breakdown.shared_tmpfs == 10  # min(shmem 10, tmpfs_used 20)
    assert snapshot.pressure is Pressure.CRITICAL


def test_cycle_without_new_collector_data_keeps_the_neutral_values(tmp_path: Path) -> None:
    snapshot = make_sampler(tmp_path=tmp_path).run_cycle()

    assert snapshot.memory.video == ()
    assert snapshot.memory.breakdown.zram == 0
    assert snapshot.pressure is Pressure.OK


def _loaded(tmp_path: Path) -> Sampler:
    sampler = make_sampler(tmp_path=tmp_path)
    sampler.collectors = replace(
        sampler.collectors,
        kernel_memory=lambda: KERNEL,
        video=lambda: VIDEO,
        psi=lambda: SEVERE_PSI,
    )
    return sampler


def test_cycle_survives_kernel_memory_raising(tmp_path: Path) -> None:
    sampler = _loaded(tmp_path)
    sampler.collectors = replace(sampler.collectors, kernel_memory=_boom)

    snapshot = sampler.run_cycle()

    assert snapshot.memory.breakdown.zram == 0
    assert snapshot.memory.video == VIDEO
    assert snapshot.pressure is Pressure.CRITICAL


def test_cycle_survives_video_raising(tmp_path: Path) -> None:
    sampler = _loaded(tmp_path)
    sampler.collectors = replace(sampler.collectors, video=_boom)

    snapshot = sampler.run_cycle()

    assert snapshot.memory.video == ()
    assert snapshot.memory.breakdown.zram == 50


def test_cycle_survives_psi_raising(tmp_path: Path) -> None:
    sampler = _loaded(tmp_path)
    sampler.collectors = replace(sampler.collectors, psi=_boom)

    snapshot = sampler.run_cycle()

    assert snapshot.pressure is Pressure.OK
    assert snapshot.memory.video == VIDEO


def test_safe_read_logs_an_os_error_only_at_debug(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        assert safe_read(_boom, neutral=0, name="probe") == 0
    assert [r.levelno for r in caplog.records] == [logging.DEBUG]


def test_safe_read_logs_a_programming_error_as_warning_with_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def broken() -> int:
        raise TypeError("bad call")

    with caplog.at_level(logging.DEBUG):
        assert safe_read(broken, neutral=0, name="probe") == 0
    (record,) = caplog.records
    assert record.levelno == logging.WARNING
    assert record.exc_info is not None
