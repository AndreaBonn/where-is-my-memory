from datetime import UTC, datetime

import pytest

from wimm.core.assemble_members import ProcessFacts, build_process_member
from wimm.core.categorize import CategoryDecision
from wimm.core.risk import RiskTarget, assess_risk
from wimm.core.tool_labels import ToolLabel
from wimm.model.enums import ActionKind, ActivityState, Category, Risk
from wimm.model.snapshot import ActionOffer, ActivityAssessment

from .helpers import process

JAVA = "/usr/bin/java"
GRADLE_CLASS = "org.gradle.launcher.daemon.bootstrap.GradleDaemon"
NOW = datetime(2026, 10, 18, tzinfo=UTC)
QEMU_ARGS = ("qemu-system-x86_64", "-name", "guest=dev-vm", "-m", "4096")


def target(*, tool: ToolLabel, activity: ActivityState = ActivityState.IDLE) -> RiskTarget:
    return RiskTarget(kind="process", category=Category.OTHER, activity=activity, tool=tool)


@pytest.mark.parametrize(
    ("tool", "risk"),
    [
        (ToolLabel.GRADLE_DAEMON, Risk.SAFE),
        (ToolLabel.KOTLIN_DAEMON, Risk.SAFE),
        (ToolLabel.LANGUAGE_SERVER, Risk.SAFE),
        (ToolLabel.ANDROID_EMULATOR, Risk.CAUTION),
        (ToolLabel.VIRTUAL_MACHINE, Risk.DANGER),
        (ToolLabel.KIND_CLUSTER, Risk.CAUTION),
        (ToolLabel.MINIKUBE_CLUSTER, Risk.CAUTION),
    ],
)
def test_tool_label_risk(tool: ToolLabel, risk: Risk) -> None:
    assessment = assess_risk(target=target(tool=tool), action=ActionKind.PROCESS_TERMINATE)
    assert assessment.level is risk
    assert assessment.consequences
    assert all(text.strip() for text in assessment.consequences)


@pytest.mark.parametrize("activity", [ActivityState.ACTIVE, ActivityState.UNKNOWN])
@pytest.mark.parametrize(
    "tool", [ToolLabel.GRADLE_DAEMON, ToolLabel.KOTLIN_DAEMON, ToolLabel.LANGUAGE_SERVER]
)
def test_tool_label_risk_safe_tools_need_attention_while_working(
    tool: ToolLabel, activity: ActivityState
) -> None:
    result = assess_risk(
        target=target(tool=tool, activity=activity), action=ActionKind.PROCESS_TERMINATE
    )
    assert result.level is Risk.CAUTION


def test_tool_label_risk_virtual_machine_is_danger_whatever_it_does() -> None:
    for activity in ActivityState:
        result = assess_risk(
            target=target(tool=ToolLabel.VIRTUAL_MACHINE, activity=activity),
            action=ActionKind.PROCESS_TERMINATE,
        )
        assert result.level is Risk.DANGER


def test_tool_label_risk_kill_of_a_virtual_machine_is_danger_of_a_daemon_is_caution() -> None:
    vm = assess_risk(target=target(tool=ToolLabel.VIRTUAL_MACHINE), action=ActionKind.PROCESS_KILL)
    daemon = assess_risk(
        target=target(tool=ToolLabel.GRADLE_DAEMON), action=ActionKind.PROCESS_KILL
    )
    assert (vm.level, daemon.level) == (Risk.DANGER, Risk.CAUTION)


def test_tool_label_risk_without_label_is_unchanged() -> None:
    plain = RiskTarget(kind="process", category=Category.OTHER, activity=ActivityState.IDLE)
    assert assess_risk(target=plain, action=ActionKind.PROCESS_TERMINATE).level is Risk.CAUTION


def facts_of(*, name: str, cmdline: tuple[str, ...]) -> ProcessFacts:
    proc = process(name=name, exe=None, cmdline=cmdline, create_time=1.0)
    idle = ActivityAssessment(state=ActivityState.IDLE, since=NOW, reason="idle")
    decision = CategoryDecision(category=Category.OTHER, reason_code="other")
    return ProcessFacts(proc=proc, decision=decision, listen_ports=frozenset(), activity=idle)


def test_member_of_a_gradle_daemon_carries_label_reason_and_safe_offer() -> None:
    facts = facts_of(name="java", cmdline=(JAVA, GRADLE_CLASS, "8.10"))

    member = build_process_member(facts=facts, desktop_categories={})

    assert (member.tool_label, member.tool_reason) == ("gradle_daemon", "background_build_daemon")
    assert member.actions == (ActionOffer(kind=ActionKind.PROCESS_TERMINATE, risk=Risk.SAFE),)


def test_member_of_a_virtual_machine_offers_a_danger_terminate() -> None:
    member = build_process_member(
        facts=facts_of(name="qemu-system-x86", cmdline=QEMU_ARGS), desktop_categories={}
    )

    assert (member.tool_label, member.tool_reason) == ("virtual_machine", "guest_memory")
    assert member.actions == (ActionOffer(kind=ActionKind.PROCESS_TERMINATE, risk=Risk.DANGER),)


def test_member_of_an_unlabelled_java_process_has_no_label() -> None:
    member = build_process_member(
        facts=facts_of(name="java", cmdline=(JAVA, "-jar", "app.jar")), desktop_categories={}
    )

    assert (member.tool_label, member.tool_reason) == (None, None)
    assert member.actions == (ActionOffer(kind=ActionKind.PROCESS_TERMINATE, risk=Risk.CAUTION),)
