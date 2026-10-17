"""A2: "Riprova adesso" reads the system again at once, without waiting for the timer."""

from tests.service.service_helpers import FakeSampler, spin_until
from wimm.config import Config
from wimm.service.app_service import AppService

LONG_INTERVAL = Config(sample_interval_s=300)


def test_retry_samples_at_once_and_a_success_clears_the_failures() -> None:
    sampler = FakeSampler()
    sampler.proceed.set()
    sampler.fail = True
    service = AppService(sampler=sampler, config=LONG_INTERVAL)
    failed: list[int] = []
    updated: list[bool] = []
    service.connect("cycle-failed", lambda s: failed.append(s.consecutive_failures))
    service.connect("snapshot-updated", lambda *_: updated.append(True))
    try:
        service.start()
        spin_until(predicate=lambda: bool(failed))
        sampler.fail = False
        before = sampler.calls

        service.retry_now()
        spin_until(predicate=lambda: bool(updated))

        assert service.consecutive_failures == 0
        assert sampler.calls == before + 1
    finally:
        service.stop()


def test_retry_after_stop_does_nothing() -> None:
    sampler = FakeSampler()
    sampler.proceed.set()
    service = AppService(sampler=sampler, config=LONG_INTERVAL)
    service.start()
    service.stop()
    before = sampler.calls

    service.retry_now()

    assert sampler.calls == before
