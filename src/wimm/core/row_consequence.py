"""The one-line consequence of an action, shared by the Disco rows and the confirmation dialog."""

from wimm.core.risk import RiskTarget, assess_risk
from wimm.core.risk_table import devdir_consequence
from wimm.model.enums import ActionKind

__all__ = ["CONSEQUENCE_SEPARATOR", "join_consequences", "row_consequence"]

CONSEQUENCE_SEPARATOR = "\n"


def join_consequences(*, consequences: tuple[str, ...]) -> str:
    """Compose consequence lines the way the Disco rows and the dialog both show them.

    A repeated line shows once, as the plan de-duplicates its consequences.
    """
    return CONSEQUENCE_SEPARATOR.join(dict.fromkeys(consequences))


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
        Every consequence of the risk assessment, joined as the dialog joins them (the devdir
        text names the rebuild command).
    """
    if action is ActionKind.DEVDIR_DELETE:
        return devdir_consequence(folder_name=folder_name, marker=marker)
    return join_consequences(consequences=assess_risk(target=target, action=action).consequences)
