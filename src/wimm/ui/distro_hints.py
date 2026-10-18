"""Texts that explain how to get the tray icon back, one per distribution family."""

from dataclasses import dataclass

from wimm.core.os_release import DistroFamily
from wimm.i18n import N_, _

STEPS_AFTER_INSTALL = N_(
    "1. Installa l'estensione scrivendo nel Terminale il comando qui sotto.\n"
    "2. Esci dalla sessione e rientra.\n"
    "3. Apri l'app «Estensioni» e attiva «AppIndicator and KStatusNotifierItem Support».\n"
    "4. L'icona compare in alto a destra entro pochi secondi."
)
UBUNTU_TITLE = N_("L'icona nella barra richiede l'estensione AppIndicator di Ubuntu")
# Checked on Ubuntu 24.04: the app is "Estensioni" in Italian, the extension
# "Ubuntu AppIndicators" with id ubuntu-appindicators@ubuntu.com.
UBUNTU_STEPS = N_(
    "1. Apri l'app «Estensioni» dal menu delle applicazioni.\n"
    "2. Attiva l'interruttore accanto a «Ubuntu AppIndicators».\n"
    "3. L'icona compare in alto a destra entro pochi secondi.\n\n"
    "Se l'app «Estensioni» non c'è, scrivi nel Terminale:"
)
UBUNTU_COMMAND = "gnome-extensions enable ubuntu-appindicators@ubuntu.com"
INSTALL_TITLE = N_("L'icona nella barra richiede l'estensione AppIndicator")
GENERIC_TITLE = N_("L'icona nella barra richiede un'estensione di GNOME Shell")
GENERIC_STEPS = N_(
    "1. Apri extensions.gnome.org, oppure l'app «Estensioni» se la tua distribuzione la offre.\n"
    "2. Cerca l'estensione «AppIndicator and KStatusNotifierItem Support» e installala.\n"
    "3. Attivala: l'icona compare in alto a destra entro pochi secondi."
)
INSTALL_COMMANDS = {
    DistroFamily.FEDORA: "sudo dnf install gnome-shell-extension-appindicator",
    DistroFamily.ARCH: "sudo pacman -S gnome-shell-extension-appindicator",
    DistroFamily.DEBIAN: "sudo apt install gnome-shell-extension-appindicator",
}


@dataclass(frozen=True)
class TrayHint:
    """Untranslated marked ``title`` and ``steps``; ``command`` is copied verbatim, if any."""

    title: str
    steps: str
    command: str | None


def tray_hint(*, family: DistroFamily) -> TrayHint:
    """Marked (not yet translated) texts for ``family``; show them through ``_()``."""
    if family is DistroFamily.UBUNTU:
        return TrayHint(title=UBUNTU_TITLE, steps=UBUNTU_STEPS, command=UBUNTU_COMMAND)
    command = INSTALL_COMMANDS.get(family)
    if command is None:
        return TrayHint(title=GENERIC_TITLE, steps=GENERIC_STEPS, command=None)
    return TrayHint(title=INSTALL_TITLE, steps=STEPS_AFTER_INSTALL, command=command)


def translated(*, hint: TrayHint) -> TrayHint:
    """The same hint with title and steps in the active language."""
    return TrayHint(title=_(hint.title), steps=_(hint.steps), command=hint.command)
