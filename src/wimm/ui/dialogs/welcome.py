"""A1: what the app does, said once on the first window, closed with "Ho capito"."""

from pathlib import Path

from gi.repository import Adw, Gtk

from wimm.first_run import is_first_run, mark_welcomed

HEADING = "Ciao! Ti aiuto a tenere il computer leggero"
# The body is centred by Adw.AlertDialog; a list reads better aligned, so it is the extra child.
POINTS = (
    "• Guardo cosa occupa la memoria e lo spazio sul disco.\n"
    "• Ti avviso quando qualcosa resta acceso senza che tu lo usi.\n"
    "• Non chiudo mai niente da solo: decidi tu, e prima vedi cosa succede.\n"
    "• Di solito mi trovi in alto a destra, nella mia icona."
)
CLOSE_RESPONSE = "close"
CLOSE_LABEL = "Ho capito"
# Shown once per session too: a marker that cannot be written must not bring it back.
_shown: set[Path] = set()


def welcome_if_first_run(*, parent: Gtk.Widget, state_dir: Path) -> None:
    """Show the welcome over ``parent`` on the first run; closing it in any way marks it seen."""
    if state_dir in _shown or not is_first_run(state_dir=state_dir):
        return
    _shown.add(state_dir)
    dialog = Adw.AlertDialog(heading=HEADING)
    dialog.set_extra_child(Gtk.Label(label=POINTS, xalign=0, wrap=True))
    dialog.add_response(CLOSE_RESPONSE, CLOSE_LABEL)
    dialog.set_default_response(CLOSE_RESPONSE)
    dialog.connect("closed", lambda *_a: mark_welcomed(state_dir=state_dir))
    dialog.present(parent)
