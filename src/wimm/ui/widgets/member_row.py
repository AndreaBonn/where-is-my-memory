"""One member of an expanded group: a short line, the technical details on request (P10)."""

from gi.repository import Adw, Gtk

from wimm.i18n import N_, _
from wimm.ui.views import MemberRow

from . import name_icon_button
from .context_menu import (
    MenuTarget,
    attach_right_click,
    install_context_actions,
    make_context_button,
    menu_label,
)

TITLE_LINES = 2
SUBTITLE_LINES = 0
DETAILS_LABEL = N_("Dettagli tecnici")
DETAILS_BUTTON_NAME = "member-details"
LINE_SEPARATOR = "\n"
FIELD_SEPARATOR = " · "
SUFFIX_SPACING = 6


def member_subtitle(*, member: MemberRow) -> str:
    """Return the technical lines of a member: ids, command, working directory, mounts."""
    head = [member.key if member.kind == "container" else _("PID {pid}").format(pid=member.key)]
    if member.started:
        head.append(_("avvio {when}").format(when=member.started))
    head += [member.memory, member.activity]
    lines = [FIELD_SEPARATOR.join(head)]
    if member.image:
        if member.state:
            lines.append(
                _("immagine {image} ({state})").format(image=member.image, state=member.state)
            )
        else:
            lines.append(_("immagine {image}").format(image=member.image))
    if member.command:
        lines.append(_("comando: {command}").format(command=member.command))
    if member.cwd:
        lines.append(_("cartella: {folder}").format(folder=member.cwd))
    if member.ports:
        lines.append(_("porte: {ports}").format(ports=member.ports))
    lines += (_("mount {path}").format(path=mount) for mount in member.mounts)
    return LINE_SEPARATOR.join(lines)


def member_summary(*, member: MemberRow) -> str:
    """The line a non-expert reads: memory, since when it runs, whether it is in use."""
    parts = [member.memory]
    if member.started:
        parts.append(_("avviato {when}").format(when=member.started))
    parts.append(member.activity)
    return FIELD_SEPARATOR.join(parts)


def target_of(*, member: MemberRow) -> MenuTarget:
    """Menu target for a member: PID only for processes."""
    pid = member.key if member.kind == "process" else None
    return MenuTarget(command=member.command, pid=pid, cwd=member.cwd)


class MemberEntry:
    """The widgets of one member, updated in place so an open menu and the focus survive."""

    def __init__(self, *, member: MemberRow) -> None:
        self.member = member
        self.widget = Adw.ActionRow(
            title=member.title,
            use_markup=False,
            title_lines=TITLE_LINES,
            subtitle_lines=SUBTITLE_LINES,
        )
        self.details = Gtk.ToggleButton(label=_(DETAILS_LABEL), valign=Gtk.Align.CENTER)
        self.details.add_css_class("flat")
        self.details.set_name(DETAILS_BUTTON_NAME)
        self.details.connect("toggled", lambda *_a: self._show_subtitle())
        self._button = make_context_button(title=member.name)
        suffix = Gtk.Box(spacing=SUFFIX_SPACING, valign=Gtk.Align.CENTER)
        suffix.append(self.details)
        suffix.append(self._button)
        self.widget.add_suffix(suffix)
        install_context_actions(owner=self.widget, target=target_of(member=member))
        attach_right_click(widget=self.widget, button=self._button)
        self._show_subtitle()

    def _show_subtitle(self) -> None:
        lines = [member_summary(member=self.member)]
        if self.details.get_active():
            lines.append(member_subtitle(member=self.member))
        self.widget.set_subtitle(LINE_SEPARATOR.join(lines))

    def update(self, *, member: MemberRow) -> None:
        """Apply ``member``; an identical member costs nothing."""
        old, self.member = self.member, member
        if old == member:
            return
        if old.title != member.title:
            self.widget.set_title(member.title)
        if old.name != member.name:
            name_icon_button(button=self._button, label=menu_label(title=member.name))
        self._show_subtitle()
        if target_of(member=old) != target_of(member=member):
            install_context_actions(owner=self.widget, target=target_of(member=member))
