from wimm.service.actions import ReclaimDelta
from wimm.service.control_protocols import StepOutcome, StepStatus
from wimm.ui.outcome import StepReport, freed_text, step_reports, summary_text

GB = 1_000_000_000


def outcomes(*statuses: StepStatus) -> tuple[StepOutcome, ...]:
    return tuple(StepOutcome(order=i, status=status) for i, status in enumerate(statuses))


def test_summary_text_is_done_only_when_every_step_ended_well() -> None:
    assert summary_text(outcomes=outcomes(StepStatus.DONE, StepStatus.ALREADY_GONE)) == "Fatto"
    failed = summary_text(outcomes=outcomes(StepStatus.DONE, StepStatus.FAILED))
    assert failed == "Alcune operazioni non sono riuscite"


def test_summary_text_names_a_process_that_does_not_answer() -> None:
    text = summary_text(outcomes=outcomes(StepStatus.DONE, StepStatus.NOT_RESPONDING))
    assert text == "Un processo non ha risposto alla chiusura"


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
    from tests.service.executor_fakes import container_step, make_plan
    from wimm.model.enums import ActionKind

    step = container_step(order=1, container_id="c1", kind=ActionKind.CONTAINER_START)
    plan = make_plan(steps=[step])
    outcomes = (StepOutcome(order=1, status=StepStatus.DONE),)
    gone = (StepOutcome(order=1, status=StepStatus.ALREADY_GONE),)

    assert step_reports(plan=plan, outcomes=outcomes)[0].status_text == "Riacceso"
    assert step_reports(plan=plan, outcomes=gone)[0].status_text == "Già acceso"
