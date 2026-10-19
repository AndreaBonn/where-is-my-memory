"""The one-line consequence of an action, shared by the Disco rows and the confirmation dialog."""

from wimm.core.risk import RiskTarget, assess_risk
from wimm.core.risk_table import devdir_consequence
from wimm.model.enums import ActionKind

__all__ = ["row_consequence"]


def row_consequence(
    *, action: ActionKind, target: RiskTarget, folder_name: str = "", marker: str = ""
) -> str:
    """Return what the user loses by `action` on `target`, in the active language.

    Parameters
    ----------
    action : ActionKind
        The action the row offers.
    target : RiskTarget
        Facts of the target, as the planner builds them.
    folder_name : str
        Name of the folder, only read for ``DEVDIR_DELETE``.
    marker : str
        Project file found beside the folder, only read for ``DEVDIR_DELETE``.

    Returns
    -------
    str
        The first consequence of the risk assessment (the devdir text names the rebuild
        command); empty when the assessment has nothing to say, as for a dangling image.
    """
    if action is ActionKind.DEVDIR_DELETE:
        return devdir_consequence(folder_name=folder_name, marker=marker)
    consequences = assess_risk(target=target, action=action).consequences
    return consequences[0] if consequences else ""
