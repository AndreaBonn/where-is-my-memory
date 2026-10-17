"""A1: what the app does, said once on the first window, closed with "Ho capito"."""

from pathlib import Path

from gi.repository import Adw, Gtk

from wimm.first_run import is_first_run, mark_welcomed
from wimm.i18n import N_, _

HEADING = N_("Ciao! Ti aiuto a tenere il computer leggero")
# The body is centred by Adw.AlertDialog; a list reads better aligned, so it is the extra child.
POINTS = N_(
    "• Guardo cosa occupa la memoria e lo spazio sul disco.\n"
    "• Ti avviso quando qualcosa resta acceso senza che tu lo usi.\n"
    "• Non chiudo mai niente da solo: decidi tu, e prima vedi cosa succede.\n"
    "• Di solito mi trovi in alto a destra, nella mia icona."
)
CLOSE_RESPONSE = "close"
CLOSE_LABEL = N_("Ho capito")
# Shown once per session too: a marker that cannot be written must not bring it back.
_shown: set[Path] = set()


def welcome_if_first_run(*, parent: Gtk.Widget, state_dir: Path) -> None:
    """Show the welcome over ``parent`` on the first run, and mark it seen at once.

    Marking on show, not on "closed": that signal waits for the close animation, which
    a compositor may never finish (window hidden, session ending), and the welcome must
    not come back.
    """
    if state_dir in _shown or not is_first_run(state_dir=state_dir):
        return
    _shown.add(state_dir)
    dialog = Adw.AlertDialog(heading=_(HEADING))
    dialog.set_extra_child(Gtk.Label(label=_(POINTS), xalign=0, wrap=True))
    dialog.add_response(CLOSE_RESPONSE, _(CLOSE_LABEL))
    dialog.set_default_response(CLOSE_RESPONSE)
    mark_welcomed(state_dir=state_dir)
    dialog.present(parent)
