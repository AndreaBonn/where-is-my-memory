import stat
import threading
import time
from pathlib import Path

import pytest

from wimm.collectors.gpu import (
    CACHE_CYCLES,
    GpuCollector,
    run_inline,
    run_nvidia_smi,
)
from wimm.model.enums import GpuVendor
from wimm.model.memory import GpuMemory

FIXTURE = Path(__file__).parents[1] / "fixtures" / "nvidia_smi_memory.txt"
MIB = 1024 * 1024
SMI = "/usr/bin/nvidia-smi"
HANG_LIMIT_S = 5.0
NON_BLOCKING_S = 1.0


class FakeRunner:
    def __init__(self, *, output: str | Exception) -> None:
        self.output = output
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> str:
        self.calls.append(argv)
        if isinstance(self.output, Exception):
            raise self.output
        return self.output


def _collector(runner: FakeRunner, *, drm: Path, smi: str | None = SMI) -> GpuCollector:
    return GpuCollector(runner=runner, which=lambda _name: smi, drm_root=drm, starter=run_inline)


def _amd_card(drm: Path, name: str, *, used: str | None, total: str | None) -> None:
    device = drm / name / "device"
    device.mkdir(parents=True)
    if used is not None:
        (device / "mem_info_vram_used").write_text(used)
    if total is not None:
        (device / "mem_info_vram_total").write_text(total)


def test_nvidia_real_output_is_converted_from_mib_to_bytes(tmp_path: Path) -> None:
    text = FIXTURE.read_text()
    used, total = (int(part) for part in text.strip().split(", "))
    runner = FakeRunner(output=text)

    result = _collector(runner, drm=tmp_path).collect()

    assert result == (GpuMemory(GpuVendor.NVIDIA, used * MIB, total * MIB),)


def test_nvidia_command_is_an_argv_list_with_the_resolved_absolute_path(tmp_path: Path) -> None:
    runner = FakeRunner(output="1, 2\n")

    _collector(runner, drm=tmp_path).collect()

    assert runner.calls == [
        [SMI, "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"]
    ]


def test_nvidia_several_gpus_give_one_entry_each_in_order(tmp_path: Path) -> None:
    runner = FakeRunner(output="100, 8000\n200, 16000\n")

    result = _collector(runner, drm=tmp_path).collect()

    assert result == (
        GpuMemory(GpuVendor.NVIDIA, 100 * MIB, 8000 * MIB),
        GpuMemory(GpuVendor.NVIDIA, 200 * MIB, 16000 * MIB),
    )


def test_nvidia_is_sampled_once_every_cache_cycles_and_cached_between(tmp_path: Path) -> None:
    runner = FakeRunner(output="10, 100\n")
    collector = _collector(runner, drm=tmp_path)

    results = [collector.collect() for _ in range(CACHE_CYCLES)]

    assert len(runner.calls) == 1
    assert all(r == (GpuMemory(GpuVendor.NVIDIA, 10 * MIB, 100 * MIB),) for r in results)
    runner.output = "20, 100\n"
    assert collector.collect() == (GpuMemory(GpuVendor.NVIDIA, 20 * MIB, 100 * MIB),)
    assert len(runner.calls) == 2


def test_missing_nvidia_smi_gives_empty_without_running_anything(tmp_path: Path) -> None:
    runner = FakeRunner(output="1, 2\n")
    collector = _collector(runner, drm=tmp_path, smi=None)

    assert collector.collect() == ()
    assert runner.calls == []


@pytest.mark.parametrize(
    "output",
    [OSError("boom"), TimeoutError("slow"), "", "garbage\n", "[N/A], [N/A]\n", "5\n", "-1, 10\n"],
)
def test_nvidia_errors_and_malformed_output_give_empty(
    tmp_path: Path, output: str | Exception
) -> None:
    result = _collector(FakeRunner(output=output), drm=tmp_path).collect()

    assert result == ()


def test_nvidia_valid_line_survives_a_malformed_one(tmp_path: Path) -> None:
    runner = FakeRunner(output="[N/A], [N/A]\n7, 70\n")

    assert _collector(runner, drm=tmp_path).collect() == (
        GpuMemory(GpuVendor.NVIDIA, 7 * MIB, 70 * MIB),
    )


def test_amd_vram_is_read_in_bytes_from_sysfs(tmp_path: Path) -> None:
    _amd_card(tmp_path, "card1", used="1073741824\n", total="8589934592\n")

    result = _collector(FakeRunner(output=""), drm=tmp_path, smi=None).collect()

    assert result == (GpuMemory(GpuVendor.AMD, 1073741824, 8589934592),)


def test_amd_cards_without_both_files_or_with_bad_values_are_skipped(tmp_path: Path) -> None:
    _amd_card(tmp_path, "card0", used="5\n", total=None)
    _amd_card(tmp_path, "card1", used=None, total="5\n")
    _amd_card(tmp_path, "card2", used="x\n", total="5\n")
    _amd_card(tmp_path, "card3", used="0\n", total="0\n")
    _amd_card(tmp_path, "card4", used="2\n", total="9\n")

    result = _collector(FakeRunner(output=""), drm=tmp_path, smi=None).collect()

    assert result == (GpuMemory(GpuVendor.AMD, 2, 9),)


def test_amd_card_with_zero_used_and_nonzero_total_is_reported(tmp_path: Path) -> None:
    _amd_card(tmp_path, "card0", used="0\n", total="9\n")

    result = _collector(FakeRunner(output=""), drm=tmp_path, smi=None).collect()

    assert result == (GpuMemory(GpuVendor.AMD, 0, 9),)


def test_amd_is_read_every_cycle_while_nvidia_stays_cached(tmp_path: Path) -> None:
    _amd_card(tmp_path, "card1", used="1\n", total="9\n")
    runner = FakeRunner(output="3, 30\n")
    collector = _collector(runner, drm=tmp_path)
    collector.collect()
    (tmp_path / "card1/device/mem_info_vram_used").write_text("4\n")

    result = collector.collect()

    assert result == (
        GpuMemory(GpuVendor.NVIDIA, 3 * MIB, 30 * MIB),
        GpuMemory(GpuVendor.AMD, 4, 9),
    )
    assert len(runner.calls) == 1


def test_no_gpu_at_all_gives_empty_tuple(tmp_path: Path) -> None:
    assert _collector(FakeRunner(output=""), drm=tmp_path, smi=None).collect() == ()


def _script(path: Path, body: str) -> str:
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


def test_run_nvidia_smi_returns_stdout_and_passes_a_minimal_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WIMM_SECRET", "leak")
    smi = _script(tmp_path / "smi", 'env > "$(dirname "$0")/env.txt"\necho "4, 40"')

    output = run_nvidia_smi([smi])

    assert output.strip() == "4, 40"
    seen = (tmp_path / "env.txt").read_text()
    assert "WIMM_SECRET" not in seen
    assert "HOME=" not in seen
    assert "LC_ALL=C" in seen


def test_run_nvidia_smi_raises_on_nonzero_exit(tmp_path: Path) -> None:
    smi = _script(tmp_path / "smi", "echo 1, 2\nexit 9")

    with pytest.raises(OSError, match="exit"):
        run_nvidia_smi([smi])


def test_run_nvidia_smi_kills_a_hung_command_at_the_timeout(tmp_path: Path) -> None:
    smi = _script(tmp_path / "smi", "exec sleep 10")
    started = time.monotonic()

    with pytest.raises(TimeoutError):
        run_nvidia_smi([smi], timeout_s=0.2)

    assert time.monotonic() - started < 3


def test_a_hung_nvidia_smi_never_blocks_collect(tmp_path: Path) -> None:
    release = threading.Event()
    calls: list[list[str]] = []

    def hung(argv: list[str]) -> str:
        calls.append(argv)
        release.wait(timeout=HANG_LIMIT_S)
        return "23, 8188\n"

    collector = GpuCollector(runner=hung, which=lambda _name: SMI, drm_root=tmp_path)
    started = time.monotonic()
    first = [collector.collect() for _ in range(CACHE_CYCLES + 1)]
    elapsed = time.monotonic() - started
    release.set()

    assert elapsed < NON_BLOCKING_S
    assert first[0] == ()
    # The refresh due at the sixth call is skipped while the first is still running.
    assert len(calls) == 1
