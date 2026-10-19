# Reference spec for Fedora. Installs the same files as the .deb (scripts/build_deb.sh)
# with the same paths, except the Python package: Fedora has no dist-packages, so it goes to
# %%{python3_sitelib}. Source: tarball from `git archive` (scripts/test_rpm.sh).
Name:           where-is-my-memory
Version:        1.0.0
Release:        1%{?dist}
Summary:        Tray monitor for forgotten containers, dev servers and apps
License:        GPL-3.0-or-later
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  python3-devel
BuildRequires:  gettext

# PyGObject, psutil and docker come from the distribution, never from PyPI (ADR-002).
# gtk4 and libadwaita ship the GI typelibs that gir1.2-* provide on Debian.
Requires:       python3 >= 3.12
Requires:       python3-gobject
Requires:       python3-psutil
Requires:       python3-docker
Requires:       gtk4
Requires:       libadwaita >= 1.5
# Mirrors the .deb Recommends.
Recommends:     gnome-shell-extension-appindicator
Recommends:     xorg-x11-utils
Suggests:       docker-cli

%description
Where Is My Memory watches the processes and Docker containers of the
current session and flags those that hold on to memory without being used.
It lives in the system tray and never acts without confirmation.

%prep
%autosetup -n %{name}-%{version}

%build
# Nothing to compile: the catalog is built in %%install, next to the files it ships with.

%install
site=%{buildroot}%{python3_sitelib}
install -d -m 755 "$site"
cp -r src/wimm "$site/wimm"
find "$site/wimm" -name '__pycache__' -type d -prune -exec rm -rf {} +
rm -rf "$site/wimm/locale"
install -d "$site/wimm/locale/en/LC_MESSAGES"
msgfmt --check-format --check-domain -o "$site/wimm/locale/en/LC_MESSAGES/wimm.mo" po/en.po
find "$site/wimm" -type d -exec chmod 755 {} +
find "$site/wimm" -type f -exec chmod 644 {} +

app_id=io.github.wimm.WhereIsMyMemory
install -D -m 755 packaging/bin/wimm %{buildroot}%{_bindir}/wimm
install -D -m 644 "data/desktop/${app_id}.autostart.desktop" \
    "%{buildroot}%{_sysconfdir}/xdg/autostart/${app_id}.desktop"
install -D -m 644 "data/desktop/${app_id}.desktop" \
    "%{buildroot}%{_datadir}/applications/${app_id}.desktop"
for size in 16 24 32 48 64 128 256 512; do
    install -D -m 644 "data/icons/hicolor/${size}x${size}/apps/${app_id}.png" \
        "%{buildroot}%{_datadir}/icons/hicolor/${size}x${size}/apps/${app_id}.png"
done
for state in normal warning critical; do
    install -D -m 644 "data/icons/hicolor/scalable/status/wimm-${state}.svg" \
        "%{buildroot}%{_datadir}/icons/hicolor/scalable/status/wimm-${state}.svg"
done
install -D -m 644 "data/metainfo/${app_id}.metainfo.xml" \
    "%{buildroot}%{_datadir}/metainfo/${app_id}.metainfo.xml"
# inspector_dbus.introspection_path() falls back to this directory.
install -D -m 644 data/dbus/io.github.wimm.Inspector1.xml \
    %{buildroot}%{_datadir}/%{name}/dbus/io.github.wimm.Inspector1.xml
install -d -m 755 %{buildroot}%{_mandir}/man1
gzip -9n -c packaging/man/wimm.1 > %{buildroot}%{_mandir}/man1/wimm.1.gz
chmod 644 %{buildroot}%{_mandir}/man1/wimm.1.gz

%files
%license LICENSE
%{python3_sitelib}/wimm/
%{_bindir}/wimm
%config(noreplace) %{_sysconfdir}/xdg/autostart/io.github.wimm.WhereIsMyMemory.desktop
%{_datadir}/applications/io.github.wimm.WhereIsMyMemory.desktop
%{_datadir}/icons/hicolor/*/apps/io.github.wimm.WhereIsMyMemory.png
%{_datadir}/icons/hicolor/scalable/status/wimm-*.svg
%{_datadir}/metainfo/io.github.wimm.WhereIsMyMemory.metainfo.xml
%{_datadir}/%{name}/
%{_mandir}/man1/wimm.1.gz

%changelog
* Mon Oct 19 2026 where-is-my-memory contributors - 1.0.0-1
- Release 1.0.0.

* Sun Oct 18 2026 where-is-my-memory contributors - 0.2.0-1
- Release 0.2.0.

* Sun Oct 18 2026 where-is-my-memory contributors - 0.1.0-1
- Release 0.1.0.
