"""A3: how to bring the tray icon back, in steps a non-expert can follow, per distribution."""

from gi.repository import Adw, Gtk

from wimm.core.os_release import DistroFamily, distro_family, read_os_release
from wimm.i18n import N_, _
from wimm.ui.distro_hints import UBUNTU_TITLE, TrayHint, translated, tray_hint

TRAY_MISSING_TEXT = UBUNTU_TITLE
HOW_LABEL = N_("Come si attiva")
HEADING = N_("Come far comparire l'icona")
CLOSE_RESPONSE = "close"
STEP_SPACING = 6
CLOSE_LABEL = N_("Ho capito")


def current_family() -> DistroFamily:
    """The family of the running system, read each time so a test can substitute the reader."""
    return distro_family(text=read_os_release())


def tray_help_dialog(*, hint: TrayHint) -> Adw.AlertDialog:
    """The steps aligned left, and the command in a selectable label so it can be copied."""
    dialog = Adw.AlertDialog(heading=_(HEADING))
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=STEP_SPACING)
    box.append(Gtk.Label(label=hint.steps, xalign=0, wrap=True))
    if hint.command is not None:
        # Not focusable: otherwise it opens with the whole command selected.
        command = Gtk.Label(label=hint.command, selectable=True, wrap=True, focusable=False)
        command.add_css_class("monospace")
        box.append(command)
    dialog.set_extra_child(box)
    dialog.add_response(CLOSE_RESPONSE, _(CLOSE_LABEL))
    return dialog


def tray_banner(*, parent: Gtk.Widget) -> Adw.Banner:
    """The hidden banner for a missing tray; "Come si attiva" opens the steps over ``parent``."""
    hint = tray_hint(family=current_family())
    banner = Adw.Banner(title=_(hint.title), button_label=_(HOW_LABEL), revealed=False)
    # Translated at click time, so a language change after the window opened still applies.
    banner.connect(
        "button-clicked", lambda *_a: tray_help_dialog(hint=translated(hint=hint)).present(parent)
    )
    return banner
