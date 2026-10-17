#!/usr/bin/env bash
# Build dist/where-is-my-memory_<version>_all.deb from the working tree (SPECIFICHE §12).
# Never installs anything on the host. Maintainer comes from WIMM_MAINTAINER, then from
# `git config user.name`/`user.email`; the build fails rather than inventing a value.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKAGE="where-is-my-memory"
APP_ID="io.github.wimm.WhereIsMyMemory"
STAGING="${ROOT}/build/deb"
DIST="${ROOT}/dist"

die() {
    echo "build_deb: $*" >&2
    exit 1
}

read_version() {
    local version
    version="$(sed -n 's/^version = "\(.*\)"$/\1/p' "${ROOT}/pyproject.toml" | head -n 1)"
    [[ -n "${version}" ]] || die "cannot read version from pyproject.toml"
    printf '%s' "${version}"
}

resolve_maintainer() {
    if [[ -n "${WIMM_MAINTAINER:-}" ]]; then
        printf '%s' "${WIMM_MAINTAINER}"
        return
    fi
    local name email
    name="$(git -C "${ROOT}" config user.name || true)"
    email="$(git -C "${ROOT}" config user.email || true)"
    if [[ -z "${name}" || -z "${email}" ]]; then
        die "no maintainer: set WIMM_MAINTAINER='Name <email>' or git config user.name and user.email"
    fi
    printf '%s <%s>' "${name}" "${email}"
}

stage_files() {
    local pydir="${STAGING}/usr/lib/python3/dist-packages"
    install -d -m 755 "${pydir}"
    cp -r "${ROOT}/src/wimm" "${pydir}/wimm"
    find "${pydir}/wimm" -name '__pycache__' -type d -prune -exec rm -rf {} +
    find "${pydir}/wimm" -type d -exec chmod 755 {} +
    find "${pydir}/wimm" -type f -exec chmod 644 {} +

    install -D -m 755 "${ROOT}/packaging/bin/wimm" "${STAGING}/usr/bin/wimm"
    install -D -m 644 "${ROOT}/data/desktop/${APP_ID}.autostart.desktop" \
        "${STAGING}/etc/xdg/autostart/${APP_ID}.desktop"
    install -D -m 644 "${ROOT}/data/desktop/${APP_ID}.desktop" \
        "${STAGING}/usr/share/applications/${APP_ID}.desktop"
    # Rendered from assets/logo by scripts/build_icons.py; keep both size lists in sync.
    local size state
    for size in 16 24 32 48 64 128 256 512; do
        install -D -m 644 "${ROOT}/data/icons/hicolor/${size}x${size}/apps/${APP_ID}.png" \
            "${STAGING}/usr/share/icons/hicolor/${size}x${size}/apps/${APP_ID}.png"
    done
    for state in normal warning critical; do
        install -D -m 644 "${ROOT}/data/icons/hicolor/scalable/status/wimm-${state}.svg" \
            "${STAGING}/usr/share/icons/hicolor/scalable/status/wimm-${state}.svg"
    done
    install -D -m 644 "${ROOT}/data/metainfo/${APP_ID}.metainfo.xml" \
        "${STAGING}/usr/share/metainfo/${APP_ID}.metainfo.xml"
    # Not listed in §12.2 but needed: inspector_dbus.introspection_path() falls back here.
    install -D -m 644 "${ROOT}/data/dbus/io.github.wimm.Inspector1.xml" \
        "${STAGING}/usr/share/${PACKAGE}/dbus/io.github.wimm.Inspector1.xml"
    install -D -m 644 "${ROOT}/packaging/debian/copyright" \
        "${STAGING}/usr/share/doc/${PACKAGE}/copyright"
}

# Escape the characters sed treats specially in a replacement with "|" as delimiter.
sed_escape() {
    printf '%s' "$1" | sed -e 's/[\\&|]/\\&/g'
}

write_control() {
    local version="$1" maintainer="$2" size
    size="$(du -sk --exclude=DEBIAN "${STAGING}" | cut -f1)"
    install -d -m 755 "${STAGING}/DEBIAN"
    sed -e "s|@VERSION@|$(sed_escape "${version}")|" \
        -e "s|@MAINTAINER@|$(sed_escape "${maintainer}")|" \
        -e "s|@INSTALLED_SIZE@|${size}|" \
        "${ROOT}/packaging/debian/control.in" > "${STAGING}/DEBIAN/control"
    install -m 755 "${ROOT}/packaging/debian/postinst" "${STAGING}/DEBIAN/postinst"
    install -m 755 "${ROOT}/packaging/debian/prerm" "${STAGING}/DEBIAN/prerm"
    install -m 755 "${ROOT}/packaging/debian/postrm" "${STAGING}/DEBIAN/postrm"
    # Debian policy 10.7.3: every file under /etc is a conffile, so admin edits survive upgrades.
    printf '/etc/xdg/autostart/%s.desktop\n' "${APP_ID}" > "${STAGING}/DEBIAN/conffiles"
    chmod 644 "${STAGING}/DEBIAN/conffiles"
}

# Native package: policy 12.7 wants a gzipped changelog. Generated from the version and
# maintainer already resolved, so it cannot disagree with DEBIAN/control.
write_changelog() {
    local version="$1" maintainer="$2" doc="${STAGING}/usr/share/doc/${PACKAGE}"
    {
        printf '%s (%s) unstable; urgency=medium\n\n' "${PACKAGE}" "${version}"
        printf '  * Release %s.\n\n' "${version}"
        printf ' -- %s  %s\n' "${maintainer}" "$(date -R)"
    } | gzip -9n > "${doc}/changelog.gz"
    chmod 644 "${doc}/changelog.gz"
}

main() {
    local version maintainer output
    version="$(read_version)"
    maintainer="$(resolve_maintainer)"
    output="${DIST}/${PACKAGE}_${version}_all.deb"

    rm -rf "${STAGING}"
    install -d -m 755 "${STAGING}" "${DIST}"
    stage_files
    write_changelog "${version}" "${maintainer}"
    write_control "${version}" "${maintainer}"
    dpkg-deb --build --root-owner-group "${STAGING}" "${output}"

    if command -v lintian >/dev/null 2>&1; then
        lintian --fail-on error "${output}"
    else
        echo "build_deb: lintian not installed, skipped" >&2
    fi
    echo "${output}"
}

main "$@"
