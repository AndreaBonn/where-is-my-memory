import pytest

from wimm.core.assemble import SystemState, Thresholds, assemble_snapshot
from wimm.model.enums import Category, GpuVendor, Pressure
from wimm.model.memory import DiskUsage, GpuMemory
from wimm.model.raw import KernelMemory, PsiSample
from wimm.model.snapshot import DockerStatus

from .assemble_helpers import DOCKER_UP, NOW, ROOT_DISK, build_input, draft, pair
from .helpers import meminfo


def test_assemble_unattributed_never_goes_negative() -> None:
    drafts = [draft("g_1", category=Category.DEV_SERVER, pids=[1])]
    heavy = pair(1, Category.DEV_SERVER, pss=5000, uss=10)

    snapshot = assemble_snapshot(inputs=build_input(drafts, pairs=[heavy]))

    assert snapshot.memory.breakdown.unattributed == 0
    assert snapshot.memory.breakdown.kernel_cache == 100 + 20 + 30 - 10


def test_assemble_unattributed_reports_memory_nobody_owns() -> None:
    drafts = [draft("g_1", category=Category.DEV_SERVER, pids=[1])]

    snapshot = assemble_snapshot(inputs=build_input(drafts, pairs=[pair(1, Category.DEV_SERVER)]))

    # total 1000 - free 100 - cache 140 - attributed 100
    assert snapshot.memory.breakdown.unattributed == 660


@pytest.mark.parametrize(
    ("available", "disks", "expected"),
    [
        (140, (ROOT_DISK,), Pressure.WARNING),
        (150, (ROOT_DISK,), Pressure.OK),
        (99, (ROOT_DISK,), Pressure.CRITICAL),
        (
            500,
            (ROOT_DISK, DiskUsage(mount="/home", total=1000, used=950, free=50)),
            Pressure.CRITICAL,
        ),
        (
            500,
            (ROOT_DISK, DiskUsage(mount="/home", total=1000, used=860, free=140)),
            Pressure.WARNING,
        ),
    ],
)
def test_assemble_pressure_is_the_worst_of_ram_and_every_disk(
    available: int, disks: tuple[DiskUsage, ...], expected: Pressure
) -> None:
    system = SystemState(mem=meminfo(mem_available=available), disks=disks, docker=DOCKER_UP)

    snapshot = assemble_snapshot(inputs=build_input([], system=system))

    assert snapshot.pressure is expected
    assert snapshot.disk == ROOT_DISK


def test_assemble_pressure_follows_the_configured_thresholds() -> None:
    system = SystemState(mem=meminfo(mem_available=300), disks=(ROOT_DISK,), docker=DOCKER_UP)
    thresholds = Thresholds(warning_pct=40, critical_pct=35)

    snapshot = assemble_snapshot(inputs=build_input([], system=system, thresholds=thresholds))

    assert snapshot.pressure is Pressure.CRITICAL


def test_assemble_passes_through_disk_reclaimable_and_docker_state() -> None:
    docker = DockerStatus(available=False, error="socket closed")
    system = SystemState(mem=meminfo(), disks=(ROOT_DISK,), docker=docker, reclaimable_disk=7400)

    snapshot = assemble_snapshot(inputs=build_input([], system=system))

    assert snapshot.reclaimable_now.disk == 7400
    assert snapshot.docker == docker
    assert snapshot.taken_at == NOW


def test_assemble_requires_at_least_one_disk() -> None:
    system = SystemState(mem=meminfo(), disks=(), docker=DOCKER_UP)

    with pytest.raises(ValueError, match="disk"):
        build_input([], system=system)


def test_assemble_uses_kernel_voices_video_and_psi_from_the_system_state() -> None:
    video = (GpuMemory(vendor=GpuVendor.AMD, used_bytes=1, total_bytes=2),)
    system = SystemState(
        mem=meminfo(),
        disks=(ROOT_DISK,),
        docker=DOCKER_UP,
        kernel=KernelMemory(zram=40, tmpfs_used=0),
        video=video,
        psi=PsiSample(some_avg60=0.0, full_avg60=9.0),
    )

    snapshot = assemble_snapshot(inputs=build_input([], system=system))

    assert snapshot.memory.breakdown.zram == 40
    assert snapshot.memory.video == video
    assert snapshot.pressure is Pressure.CRITICAL
    plain = assemble_snapshot(inputs=build_input([]))
    assert plain.pressure is Pressure.OK
    assert plain.memory.video == ()
