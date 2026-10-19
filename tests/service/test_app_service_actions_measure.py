from tests.core.planning_helpers import group, proc, snapshot
from tests.service.app_service_actions_helpers import (
    PID,
    RigFactory,
    rigs,
    terminate,
)
from tests.service.service_helpers import (
    TIMEOUT_S,
    spin_for,
    spin_until,
    with_free_space,
)
from wimm.model.enums import Category
from wimm.service.actions import ReclaimDelta

__all__ = ["rigs"]


def test_reclaim_delta_is_measured_on_a_later_snapshot_after_an_immediate_cycle(
    rigs: RigFactory,
) -> None:
    base = snapshot(group(gid="dev", category=Category.DEV_SERVER, members=(proc(pid=PID),)))
    before = with_free_space(snapshot=base, available=400, free=900)
    after = with_free_space(snapshot=base, available=700, free=950)
    rig = rigs.build(base=before)
    plan = rig.service.plan(request=terminate())
    calls = rig.sampler.calls
    rig.sampler.current = after

    rig.service.execute(plan_id=plan.plan_id, typed_confirmation=None)
    spin_until(predicate=lambda: bool(rig.measured))

    assert rig.measured == [(plan.plan_id, ReclaimDelta(freed_ram=300, freed_disk=50))]
    assert rig.sampler.calls > calls
    assert rig.service.snapshot() == after


def test_a_sample_already_in_flight_when_the_delay_elapses_is_not_used_for_the_delta(
    rigs: RigFactory,
) -> None:
    base = snapshot(group(gid="dev", category=Category.DEV_SERVER, members=(proc(pid=PID),)))
    before = with_free_space(snapshot=base, available=400, free=900)
    after = with_free_space(snapshot=base, available=700, free=950)
    rig = rigs.build(base=before)
    plan = rig.service.plan(request=terminate())
    rig.sampler.proceed.clear()
    rig.sampler.entered.clear()
    rig.service.execute(plan_id=plan.plan_id, typed_confirmation=None)
    spin_until(predicate=lambda: bool(rig.finished))
    assert rig.sampler.entered.wait(timeout=TIMEOUT_S)

    rig.sampler.current = after
    spin_for(seconds=0.1)
    assert rig.measured == []
    rig.sampler.proceed.set()
    spin_until(predicate=lambda: bool(rig.measured))

    assert rig.measured == [(plan.plan_id, ReclaimDelta(freed_ram=300, freed_disk=50))]


def test_each_plan_is_measured_against_its_own_baseline(rigs: RigFactory) -> None:
    base = snapshot(group(gid="dev", category=Category.DEV_SERVER, members=(proc(pid=PID),)))
    s0 = with_free_space(snapshot=base, available=400, free=900)
    s1 = with_free_space(snapshot=base, available=500, free=910)
    s2 = with_free_space(snapshot=base, available=700, free=950)
    rig = rigs.build(base=s0)
    first = rig.service.plan(request=terminate())
    second = rig.service.plan(request=terminate())
    rig.sampler.proceed.clear()
    rig.sampler.entered.clear()
    rig.sampler.current = s1
    rig.service.execute(plan_id=first.plan_id, typed_confirmation=None)
    spin_until(predicate=lambda: bool(rig.finished))
    assert rig.sampler.entered.wait(timeout=TIMEOUT_S)
    spin_for(seconds=0.1)

    # `second` queues behind the sample in flight, which will publish s1.
    rig.service.execute(plan_id=second.plan_id, typed_confirmation=None)
    rig.sampler.current = s2
    rig.sampler.proceed.set()
    spin_until(predicate=lambda: len(rig.measured) == 2)

    assert rig.measured == [
        (first.plan_id, ReclaimDelta(freed_ram=300, freed_disk=50)),
        (second.plan_id, ReclaimDelta(freed_ram=200, freed_disk=40)),
    ]
