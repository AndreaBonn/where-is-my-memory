import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const BUS_NAME = 'io.github.wimm.Focus';
const OBJECT_PATH = '/io/github/wimm/Focus';
const INTERFACE_VERSION = 1;

const INTERFACE_XML = `
<node>
  <interface name="io.github.wimm.Focus1">
    <property name="FocusedPid" type="u" access="read"/>
    <property name="Version" type="u" access="read"/>
  </interface>
</node>`;

export default class WimmFocusExtension extends Extension {
    enable() {
        this._pid = 0;
        this._exported = Gio.DBusExportedObject.wrapJSObject(INTERFACE_XML, this);
        this._exported.export(Gio.DBus.session, OBJECT_PATH);
        this._ownerId = Gio.bus_own_name_on_connection(
            Gio.DBus.session, BUS_NAME, Gio.BusNameOwnerFlags.NONE, null, null);
        this._focusSignal = global.display.connect(
            'notify::focus-window', () => this._update());
        this._update();
    }

    disable() {
        if (this._focusSignal) {
            global.display.disconnect(this._focusSignal);
            this._focusSignal = null;
        }
        if (this._ownerId) {
            Gio.bus_unown_name(this._ownerId);
            this._ownerId = 0;
        }
        if (this._exported) {
            this._exported.unexport();
            this._exported = null;
        }
    }

    get FocusedPid() {
        return this._pid;
    }

    get Version() {
        return INTERFACE_VERSION;
    }

    _update() {
        const win = global.display.focus_window;
        const pid = win ? win.get_pid() : 0;
        const next = pid > 0 ? pid : 0;
        if (next === this._pid)
            return;
        this._pid = next;
        this._exported.emit_property_changed(
            'FocusedPid', GLib.Variant.new_uint32(next));
        this._exported.flush();
    }
}
