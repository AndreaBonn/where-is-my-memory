"""The footer shown under every page: copyright sign and the author's name."""

from gi.repository import Gtk

from wimm.i18n import _

from . import name_icon_button

COPYRIGHT_SIGN = "©"
AUTHOR_NAME = "Andrea Bonacci"
AUTHOR_URL = "https://github.com/AndreaBonn"
FOOTER_SPACING = 2
FOOTER_MARGIN = 2


def app_footer() -> Gtk.Box:
    """A centred "© Andrea Bonacci" line; the name opens the author's GitHub profile."""
    box = Gtk.Box(spacing=FOOTER_SPACING, halign=Gtk.Align.CENTER)
    box.set_margin_top(FOOTER_MARGIN)
    box.set_margin_bottom(FOOTER_MARGIN)
    sign = Gtk.Label(label=COPYRIGHT_SIGN)
    sign.add_css_class("dim-label")
    box.append(sign)
    link = Gtk.LinkButton(uri=AUTHOR_URL, label=AUTHOR_NAME)
    name_icon_button(button=link, label=_("Apri il profilo GitHub di Andrea Bonacci"))
    box.append(link)
    return box
