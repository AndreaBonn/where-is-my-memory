import pytest

from wimm.core.planning_disk import TRASH_PHRASE
from wimm.core.risk import RiskTarget, assess_risk
from wimm.i18n import _
from wimm.model.enums import ActionKind, ActivityState, Category

pytestmark = pytest.mark.usefixtures("english")


def test_consequences_are_translated_when_the_plan_is_assessed() -> None:
    target = RiskTarget(kind="process", category=Category.DEV_PROCESS, activity=ActivityState.IDLE)

    assessment = assess_risk(target=target, action=ActionKind.PROCESS_TERMINATE)

    assert assessment.consequences == ("The server stops.",)


def test_volume_consequence_keeps_the_volume_names() -> None:
    target = RiskTarget(kind="compose_project", volume_names=("pgdata", "redis"))

    assessment = assess_risk(target=target, action=ActionKind.COMPOSE_DOWN_VOLUMES)

    assert assessment.consequences == (
        "The data in the volumes pgdata, redis is permanently deleted.",
    )


def test_volume_consequence_without_names_says_linked_to_the_project() -> None:
    target = RiskTarget(kind="compose_project")

    assessment = assess_risk(target=target, action=ActionKind.COMPOSE_DOWN_VOLUMES)

    assert "linked to the project" in assessment.consequences[0]


def test_container_stop_lists_both_consequences() -> None:
    target = RiskTarget(kind="container", is_running=True)

    assessment = assess_risk(target=target, action=ActionKind.CONTAINER_STOP)

    assert assessment.consequences == (
        "The container stops; its data and configuration remain.",
        "If the container does not stop by itself, Docker ends it after 10 seconds.",
    )


def test_trash_phrase_is_translated_for_the_typed_confirmation() -> None:
    assert _(TRASH_PHRASE) == "Trash"
