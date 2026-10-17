from wimm.model.actions import ACTION_TARGET_SHAPES, ActionRequest
from wimm.model.enums import GroupId, TargetId, TargetShape
from wimm.ui.views import GroupRow


def request_for_row(*, row: GroupRow) -> ActionRequest | None:
    """Build the request behind the primary button of a group row.

    A target-shaped action (one process, one container) points at the member that
    offers it; None when the row has no button or no member offers the action.
    """
    action = row.primary_action
    if action is None:
        return None
    shape = ACTION_TARGET_SHAPES[action.kind]
    if shape is TargetShape.GROUP:
        return ActionRequest(kind=action.kind, group_id=GroupId(row.id))
    if shape is TargetShape.NONE:
        return ActionRequest(kind=action.kind)
    for member in row.members:
        if any(offer.kind is action.kind for offer in member.actions):
            return ActionRequest(kind=action.kind, target_id=TargetId(member.key))
    return None
