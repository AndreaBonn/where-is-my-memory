from tests.service.executor_fakes import (
    builder_step,
    container_step,
    image_step,
    make_plan,
    process_step,
)
from wimm.model.actions import Plan, PlanStep
from wimm.model.enums import ActionKind
from wimm.service.actions import ReclaimDelta
from wimm.service.control_protocols import StepOutcome, StepStatus
from wimm.ui.outcome import StepReport, freed_text, step_reports, summary_text

GB = 1_000_000_000


def outcomes(*statuses: StepStatus) -> tuple[StepOutcome, ...]:
    return tuple(StepOutcome(order=i, status=status) for i, status in enumerate(statuses))


def plan_of(*steps: PlanStep) -> Plan:
    return make_plan(steps=steps)


def stops(count: int) -> Plan:
    return plan_of(*(process_step(order=i + 1, pid=i + 1) for i in range(count)))


def test_summary_names_the_subject_and_what_happened() -> None:
    plan = plan_of(
        process_step(order=1, pid=1),
        container_step(order=2, container_id="c1", kind=ActionKind.CONTAINER_STOP),
    )
    done = outcomes(StepStatus.DONE, StepStatus.ALREADY_GONE)

    assert summary_text(outcomes=done, plan=plan, subject="whitebox") == (
        "whitebox: arresto completato"
    )


def test_summary_of_a_single_step_uses_its_label_when_no_subject_is_known() -> None:
    done = outcomes(StepStatus.DONE)

    assert summary_text(outcomes=done, plan=stops(1)) == "proc 1: arresto completato"


def test_summary_without_a_subject_counts_the_items() -> None:
    done = outcomes(StepStatus.DONE, StepStatus.DONE, StepStatus.DONE)

    assert summary_text(outcomes=done, plan=stops(3)) == "3 elementi: arresto completato"
    assert summary_text(outcomes=outcomes(StepStatus.DONE, StepStatus.ALREADY_GONE)) == (
        "2 elementi: operazione completata"
    )


def test_summary_uses_a_verb_fitting_each_action_family() -> None:
    done = outcomes(StepStatus.DONE)
    kill = plan_of(process_step(order=1, pid=1, kind=ActionKind.PROCESS_KILL))
    remove = plan_of(image_step(order=1, image_id="img1"))
    clean = plan_of(builder_step(order=1))
    start = plan_of(container_step(order=1, container_id="c1", kind=ActionKind.CONTAINER_START))

    assert summary_text(outcomes=done, plan=kill) == "proc 1: chiusura forzata completata"
    assert summary_text(outcomes=done, plan=remove) == "img1: rimozione completata"
    assert summary_text(outcomes=done, plan=clean) == "build cache: pulizia completata"
    assert summary_text(outcomes=done, plan=start) == "c1: riavvio completato"


def test_a_partial_result_counts_what_worked_and_what_did_not() -> None:
    four = outcomes(StepStatus.DONE, StepStatus.DONE, StepStatus.DONE, StepStatus.NOT_RESPONDING)
    mixed = outcomes(
        StepStatus.DONE,
        StepStatus.ALREADY_GONE,
        StepStatus.NOT_RESPONDING,
        StepStatus.NOT_RESPONDING,
        StepStatus.FAILED,
    )

    assert summary_text(outcomes=four, plan=stops(4)) == "3 su 4 fermati, 1 non risponde"
    assert summary_text(outcomes=mixed, plan=stops(5)) == (
        "2 su 5 fermati, 2 non rispondono, 1 non riuscito"
    )
    failed = outcomes(StepStatus.DONE, StepStatus.FAILED, StepStatus.FAILED)
    assert summary_text(outcomes=failed, plan=stops(3)) == "1 su 3 fermati, 2 non riusciti"


def test_a_single_step_that_failed_names_its_target() -> None:
    stuck = summary_text(outcomes=outcomes(StepStatus.NOT_RESPONDING), plan=stops(1))
    failed = summary_text(outcomes=outcomes(StepStatus.FAILED), plan=stops(1), subject="firefox")

    assert stuck == "proc 1: non risponde"
    assert failed == "firefox: operazione non riuscita"


def test_freed_text_reports_ram_disk_and_both() -> None:
    assert freed_text(delta=ReclaimDelta(freed_ram=1_100_000_000, freed_disk=0)) == (
        "Liberati 1,1 GB di RAM"
    )
    assert freed_text(delta=ReclaimDelta(freed_ram=0, freed_disk=2 * GB)) == (
        "Liberati 2,0 GB di disco"
    )
    both = freed_text(delta=ReclaimDelta(freed_ram=GB, freed_disk=GB))
    assert both == "Liberati 1,0 GB di RAM e 1,0 GB di disco"


def test_freed_text_is_none_when_nothing_was_freed() -> None:
    assert freed_text(delta=ReclaimDelta(freed_ram=-5, freed_disk=0)) is None


def test_step_reports_without_a_plan_use_a_generic_label_and_offer_no_force() -> None:
    (report,) = step_reports(plan=None, outcomes=outcomes(StepStatus.NOT_RESPONDING))
    assert report == StepReport(label="Passo 0", status=StepStatus.NOT_RESPONDING, pid=None)
    assert not report.can_force


def test_a_start_reads_as_started_not_closed() -> None:
    step = container_step(order=1, container_id="c1", kind=ActionKind.CONTAINER_START)
    plan = make_plan(steps=[step])
    outcomes = (StepOutcome(order=1, status=StepStatus.DONE),)
    gone = (StepOutcome(order=1, status=StepStatus.ALREADY_GONE),)

    assert step_reports(plan=plan, outcomes=outcomes)[0].status_text == "Riacceso"
    assert step_reports(plan=plan, outcomes=gone)[0].status_text == "Già acceso"


def test_a_target_that_was_already_gone_is_not_credited_to_the_action() -> None:
    gone = outcomes(StepStatus.ALREADY_GONE)
    start = plan_of(container_step(order=1, container_id="c1", kind=ActionKind.CONTAINER_START))
    remove = plan_of(image_step(order=1, image_id="img1"))

    assert summary_text(outcomes=gone, plan=stops(1), subject="firefox") == "firefox: già chiuso"
    assert summary_text(outcomes=gone, plan=start) == "c1: già acceso"
    assert summary_text(outcomes=gone, plan=remove) == "img1: già rimosso"
    both_gone = outcomes(StepStatus.ALREADY_GONE, StepStatus.ALREADY_GONE)
    assert summary_text(outcomes=both_gone) == "2 elementi: già a posto"
    mixed = outcomes(StepStatus.ALREADY_GONE, StepStatus.DONE)
    assert summary_text(outcomes=mixed, plan=stops(2), subject="x") == "x: arresto completato"


def test_no_outcome_at_all_says_nothing_was_done() -> None:
    assert summary_text(outcomes=()) == "Nessuna operazione eseguita"


def test_a_partial_result_over_mixed_families_uses_the_generic_participle() -> None:
    plan = plan_of(process_step(order=1, pid=1), image_step(order=2, image_id="img1"))

    text = summary_text(outcomes=outcomes(StepStatus.DONE, StepStatus.FAILED), plan=plan)

    assert text == "1 su 2 completati, 1 non riuscito"
