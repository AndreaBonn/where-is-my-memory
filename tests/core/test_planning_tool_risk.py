from dataclasses import replace

from wimm.core.planning_drafts import process_draft
from wimm.core.tool_labels import ToolLabel, ToolReason
from wimm.model.enums import ActionKind, Category, Risk

from .planning_helpers import proc


def test_process_draft_assesses_a_virtual_machine_as_danger() -> None:
    plain = proc(pid=41, name="qemu-system-x86_64", category=Category.OTHER)
    vm = replace(
        plain,
        tool_label=ToolLabel.VIRTUAL_MACHINE.value,
        tool_reason=ToolReason.GUEST_MEMORY.value,
    )
    # The confirmation dialog must agree with the badge of the list, which uses the label.
    assert process_draft(member=vm, kind=ActionKind.PROCESS_TERMINATE).assessed.level is Risk.DANGER
    assert process_draft(member=plain, kind=ActionKind.PROCESS_TERMINATE).assessed.level is not (
        Risk.DANGER
    )
