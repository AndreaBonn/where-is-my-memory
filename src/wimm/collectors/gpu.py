import logging
import shutil
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

LOGGER = logging.getLogger(__name__)
VENDOR_NVIDIA = "nvidia"
VENDOR_AMD = "amd"
NVIDIA_SMI = "nvidia-smi"
NVIDIA_QUERY_ARGS = ("--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits")
NVIDIA_TIMEOUT_S = 2.0
NVIDIA_ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"}
CACHE_CYCLES = 5
MIB = 1024 * 1024
DRM_ROOT = Path("/sys/class/drm")
AMD_USED_GLOB = "card*/device/mem_info_vram_used"
AMD_TOTAL_FILE = "mem_info_vram_total"


class GpuMemory(NamedTuple):
    """Dedicated video memory of one GPU, in bytes."""

    vendor: str
    used_bytes: int
    total_bytes: int


Runner = Callable[[list[str]], str]
Starter = Callable[[Callable[[], None]], None]


def start_daemon(task: Callable[[], None]) -> None:
    """Run off the sampling cycle: a driver stuck in D-state outlives any subprocess timeout."""
    threading.Thread(target=task, name="wimm-nvidia-smi", daemon=True).start()


def run_inline(task: Callable[[], None]) -> None:
    task()


def run_nvidia_smi(
    argv: list[str],
    *,
    timeout_s: float = NVIDIA_TIMEOUT_S,
    run: Callable[..., "subprocess.CompletedProcess[str]"] = subprocess.run,
) -> str:
    """Run the command with a minimal environment; raise on timeout or non-zero exit."""
    try:
        done = run(
            argv, capture_output=True, text=True, timeout=timeout_s, env=NVIDIA_ENV, check=False
        )
    except subprocess.TimeoutExpired as error:
        raise TimeoutError(f"{NVIDIA_SMI} exceeded {timeout_s} s") from error
    if done.returncode != 0:
        raise OSError(f"{NVIDIA_SMI} exit {done.returncode}")
    return done.stdout


def parse_nvidia(text: str) -> tuple[GpuMemory, ...]:
    """Parse ``used, total`` lines in MiB; lines that are not two non-negative ints are skipped."""
    found = []
    for line in text.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 2 or not all(part.isdecimal() for part in parts):
            continue
        found.append(
            GpuMemory(
                vendor=VENDOR_NVIDIA,
                used_bytes=int(parts[0]) * MIB,
                total_bytes=int(parts[1]) * MIB,
            )
        )
    return tuple(found)


def _read_int(*, path: Path) -> int | None:
    try:
        text = path.read_text().strip()
    except OSError:
        return None
    return int(text) if text.isdecimal() else None


def read_amd(*, drm_root: Path) -> tuple[GpuMemory, ...]:
    found = []
    for used_path in sorted(drm_root.glob(AMD_USED_GLOB)):
        used = _read_int(path=used_path)
        total = _read_int(path=used_path.with_name(AMD_TOTAL_FILE))
        if used is not None and total:
            found.append(GpuMemory(vendor=VENDOR_AMD, used_bytes=used, total_bytes=total))
    return tuple(found)


class GpuCollector:
    """VRAM per dedicated GPU; the costly NVIDIA call runs once every ``CACHE_CYCLES`` calls.

    The call runs through ``starter``, in a daemon thread by default, and ``collect`` returns
    the last finished reading: a hung ``nvidia-smi`` costs a stale value, never the cycle.
    """

    def __init__(
        self,
        *,
        runner: Runner = run_nvidia_smi,
        which: Callable[[str], str | None] = shutil.which,
        drm_root: Path = DRM_ROOT,
        starter: Starter = start_daemon,
    ) -> None:
        self._runner = runner
        self._starter = starter
        self._lock = threading.Lock()
        self._running = False
        self._smi = which(NVIDIA_SMI)
        self._drm_root = drm_root
        self._calls = 0
        self._nvidia: tuple[GpuMemory, ...] = ()

    def collect(self) -> tuple[GpuMemory, ...]:
        if self._calls % CACHE_CYCLES == 0:
            self._refresh_nvidia()
        self._calls += 1
        with self._lock:
            nvidia = self._nvidia
        return nvidia + self._amd()

    def _refresh_nvidia(self) -> None:
        with self._lock:
            if self._smi is None or self._running:
                return
            self._running = True
        self._starter(self._sample_nvidia)

    def _sample_nvidia(self) -> None:
        found: tuple[GpuMemory, ...] = ()
        try:
            found = parse_nvidia(self._runner([str(self._smi), *NVIDIA_QUERY_ARGS]))
        except Exception as error:
            LOGGER.debug("NVIDIA memory not readable: %s", error)
        with self._lock:
            self._nvidia = found
            self._running = False

    def _amd(self) -> tuple[GpuMemory, ...]:
        try:
            return read_amd(drm_root=self._drm_root)
        except OSError as error:
            LOGGER.debug("AMD memory not readable: %s", error)
            return ()
