import threading
from pathlib import Path

import pytest

from tests.service.service_helpers import FakeSampler, spin_until
from wimm.config import Config
from wimm.model.actions import Plan
from wimm.paths import UserPaths
from wimm.service.actions import ActionSetup
from wimm.service.app_service import AppService
from wimm.service.control_protocols import StepOutcome

OWNER_UID = 1000


class RecordingExecutor:
    def __init__(self) -> None:
        self.configs: list[tuple[Config, int]] = []

    def execute(self, *, plan: Plan) -> tuple[StepOutcome, ...]:
        return ()

    def apply_config(self, *, config: Config) -> None:
        self.configs.append((config, threading.get_ident()))


@pytest.fixture
def paths(tmp_path: Path) -> UserPaths:
    return UserPaths(
        config_dir=tmp_path / "config", state_dir=tmp_path / "state", cache_dir=tmp_path / "cache"
    )


def started_service(*, executor: RecordingExecutor) -> tuple[AppService, FakeSampler]:
    sampler = FakeSampler()
    sampler.proceed.set()
    setup = ActionSetup(executor=executor, owner_uid=OWNER_UID)
    service = AppService(sampler=sampler, config=Config(), actions=setup)
    service.start()
    spin_until(predicate=lambda: service.snapshot() is not None)
    return service, sampler


def test_update_config_applies_to_sampler_and_executor_on_the_worker(
    paths: UserPaths, tmp_path: Path
) -> None:
    executor = RecordingExecutor()
    service, sampler = started_service(executor=executor)
    try:
        service.update_config(changes={"cpu_active_threshold_pct": 5}, paths=paths, home=tmp_path)
        spin_until(predicate=lambda: bool(sampler.configs) and bool(executor.configs))
        assert [config for config, _ in sampler.configs] == [service.config()]
        assert service.config().cpu_active_threshold_pct == 5
        assert [config for config, _ in executor.configs] == [service.config()]
        worker = sampler.cycle_threads[0]
        assert worker != threading.get_ident()
        assert sampler.configs[0][1] == worker
        assert executor.configs[0][1] == worker
    finally:
        service.stop()


def test_update_config_without_changes_does_not_touch_sampler_or_executor(
    paths: UserPaths, tmp_path: Path
) -> None:
    executor = RecordingExecutor()
    service, sampler = started_service(executor=executor)
    try:
        service.update_config(changes={"cpu_active_threshold_pct": 5}, paths=paths, home=tmp_path)
        spin_until(predicate=lambda: len(sampler.configs) == 1)
        cycles = sampler.calls
        service.update_config(changes={"cpu_active_threshold_pct": 5}, paths=paths, home=tmp_path)
        # The cycle update_config asked for may still be running: retry until one starts.
        spin_until(predicate=lambda: bool(service.request_cycle()) and sampler.calls > cycles)
        assert len(sampler.configs) == 1
        assert len(executor.configs) == 1
    finally:
        service.stop()


def test_update_config_rejected_field_is_not_applied(paths: UserPaths, tmp_path: Path) -> None:
    executor = RecordingExecutor()
    service, sampler = started_service(executor=executor)
    try:
        service.update_config(changes={"sample_interval_s": 5}, paths=paths, home=tmp_path)
        service.request_cycle()
        spin_until(predicate=lambda: sampler.calls > 1)
        assert sampler.configs == []
    finally:
        service.stop()


def test_update_config_samples_again_right_after_applying(paths: UserPaths, tmp_path: Path) -> None:
    # A name added to the protected list must show in the window now, not one interval later.
    executor = RecordingExecutor()
    service, sampler = started_service(executor=executor)
    try:
        cycles_before = sampler.calls
        service.update_config(
            changes={"extra_protected_names": ["postgres"]}, paths=paths, home=tmp_path
        )
        spin_until(predicate=lambda: sampler.calls > cycles_before)
        assert bool(sampler.configs)
    finally:
        service.stop()


def test_update_config_after_stop_saves_nothing(paths: UserPaths, tmp_path: Path) -> None:
    from wimm.service.errors import InvalidRequest

    service, _ = started_service(executor=RecordingExecutor())
    service.stop()

    with pytest.raises(InvalidRequest):
        service.update_config(changes={"cpu_active_threshold_pct": 5}, paths=paths, home=tmp_path)

    assert service.config() == Config()
    assert not (paths.config_dir / "config.json").exists()
