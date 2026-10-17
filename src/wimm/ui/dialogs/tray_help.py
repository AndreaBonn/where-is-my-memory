"""A3: how to bring the tray icon back, in steps a non-expert can follow (Ubuntu 24.04)."""

from gi.repository import Adw, Gtk

TRAY_MISSING_TEXT = "L'icona nella barra richiede l'estensione AppIndicator di Ubuntu"
HOW_LABEL = "Come si attiva"
HEADING = "Come far comparire l'icona"
# Checked on Ubuntu 24.04: the app is "Estensioni" in Italian, the extension
# "Ubuntu AppIndicators" with id ubuntu-appindicators@ubuntu.com.
STEPS = (
    "1. Apri l'app «Estensioni» dal menu delle applicazioni.\n"
    "2. Attiva l'interruttore accanto a «Ubuntu AppIndicators».\n"
    "3. L'icona compare in alto a destra entro pochi secondi.\n\n"
    "Se l'app «Estensioni» non c'è, scrivi nel Terminale:"
)
COMMAND = "gnome-extensions enable ubuntu-appindicators@ubuntu.com"
CLOSE_RESPONSE = "close"
STEP_SPACING = 6
CLOSE_LABEL = "Ho capito"


def tray_help_dialog() -> Adw.AlertDialog:
    """The steps aligned left, and the command in a selectable label so it can be copied."""
    dialog = Adw.AlertDialog(heading=HEADING)
    # Not focusable: otherwise it opens with the whole command selected.
    command = Gtk.Label(label=COMMAND, selectable=True, wrap=True, focusable=False)
    command.add_css_class("monospace")
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=STEP_SPACING)
    box.append(Gtk.Label(label=STEPS, xalign=0, wrap=True))
    box.append(command)
    dialog.set_extra_child(box)
    dialog.add_response(CLOSE_RESPONSE, CLOSE_LABEL)
    return dialog


def tray_banner(*, parent: Gtk.Widget) -> Adw.Banner:
    """The hidden banner for a missing tray; "Come si attiva" opens the steps over ``parent``."""
    banner = Adw.Banner(title=TRAY_MISSING_TEXT, button_label=HOW_LABEL, revealed=False)
    banner.connect("button-clicked", lambda *_a: tray_help_dialog().present(parent))
    return banner
