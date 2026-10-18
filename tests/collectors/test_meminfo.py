import subprocess
from pathlib import Path

import pytest

from wimm.collectors.meminfo import MEMINFO_FIELDS, collect_meminfo, parse_meminfo

FIXTURES = Path(__file__).parents[1] / "fixtures"
KIB = 1024
TOLERANCE = 0.02


def test_parse_meminfo_real_fixture() -> None:
    text = (FIXTURES / "meminfo_real.txt").read_text()
    parsed = parse_meminfo(text=text)
    assert parsed.mem_total == 41_744_506_880
    assert parsed.mem_available == 3_262_263_296
    assert parsed.swap_free == 643_072


@pytest.mark.parametrize("text", ["", "MemTotal: -1 kB"])
def test_parse_meminfo_rejects_invalid_data(text: str) -> None:
    with pytest.raises(ValueError):
        parse_meminfo(text=text)


def test_collect_meminfo_success_and_failure(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    result = collect_meminfo(path=FIXTURES / "meminfo_real.txt")
    assert result.data is not None and result.data.mem_total > 0
    assert result.error is None
    failed = collect_meminfo(path=tmp_path / "missing")
    assert failed.data is None and failed.error
    assert "WARNING" in caplog.text


@pytest.mark.integration
def test_meminfo_matches_free() -> None:
    memory = parse_meminfo(text=Path("/proc/meminfo").read_text())
    output = subprocess.run(
        args=["/usr/bin/free", "-b"], capture_output=True, text=True, check=True, timeout=5
    ).stdout
    row = next(line.split() for line in output.splitlines() if line.startswith("Mem:"))
    total = int(row[1])
    # Spec DoD 2 bounds the error at 2% of the machine's RAM: MemAvailable moves between
    # the two reads, and under pressure a relative bound on it alone flakes (52 MB on 886 MB).
    for actual, expected in ((memory.mem_total, total), (memory.mem_available, int(row[-1]))):
        assert abs(actual - expected) / total < TOLERANCE


def test_parse_meminfo_all_counters_and_extra_fields() -> None:
    text = "\n".join(
        [
            "MemTotal: 90 kB",
            "MemFree: 10 kB",
            "MemAvailable: 30 kB",
            "Cached: 20 kB",
            "Buffers: 1 kB",
            "SReclaimable: 2 kB",
            "Shmem: 3 kB",
            "SwapTotal: 0 kB",
            "SwapFree: 0 kB",
            "HugePages_Total: 0",
        ]
    )
    result = parse_meminfo(text=text)
    assert (
        result.mem_total,
        result.mem_free,
        result.mem_available,
        result.cached,
        result.buffers,
        result.s_reclaimable,
        result.shmem,
        result.swap_total,
        result.swap_free,
    ) == tuple(value * KIB for value in (90, 10, 30, 20, 1, 2, 3, 0, 0))


@pytest.mark.parametrize("replacement", ["MemTotal: -1 kB", "MemTotal: 1 MB", "MemTotal: nope kB"])
def test_parse_meminfo_rejects_invalid_counter_in_complete_input(replacement: str) -> None:
    lines = (FIXTURES / "meminfo_real.txt").read_text().splitlines()
    text = "\n".join(replacement if line.startswith("MemTotal:") else line for line in lines)
    with pytest.raises(ValueError, match="nope" if "nope" in replacement else None):
        parse_meminfo(text=text)


def test_parse_meminfo_host_fixture_reads_kernel_counters() -> None:
    parsed = parse_meminfo(text=(FIXTURES / "meminfo_host.txt").read_text())
    assert parsed.s_unreclaim == 803_632 * KIB
    assert parsed.kernel_stack == 70_800 * KIB
    assert parsed.page_tables == 196_548 * KIB
    assert parsed.zswap == 0


def test_parse_meminfo_reads_zswap_when_present_and_zero_when_absent() -> None:
    lines = (FIXTURES / "meminfo_host.txt").read_text().splitlines()
    with_zswap = "\n".join("Zswap: 512 kB" if line.startswith("Zswap:") else line for line in lines)
    without_zswap = "\n".join(line for line in lines if not line.startswith("Zswap"))
    assert parse_meminfo(text=with_zswap).zswap == 512 * KIB
    assert parse_meminfo(text=without_zswap).zswap == 0


def test_parse_meminfo_missing_kernel_counters_are_zero() -> None:
    required = (*MEMINFO_FIELDS,)
    text = "\n".join(f"{name}: 1 kB" for name in required)
    parsed = parse_meminfo(text=text)
    assert (parsed.s_unreclaim, parsed.kernel_stack, parsed.page_tables, parsed.zswap) == (0,) * 4
