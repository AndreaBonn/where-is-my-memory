#!/usr/bin/env bash
# Install the built .deb in a throwaway ubuntu:24.04 container and check it (SPECIFICHE §12, T-2.3).
# Touches nothing on the host except the one container named wimm-test-deb, which is removed on exit.
# Steps: apt install with dependencies, §12.2 files present, `wimm --version`, lintian
# (errors fail, warnings are reported), apt remove, no leftovers.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKAGE="where-is-my-memory"
APP_ID="io.github.wimm.WhereIsMyMemory"
CONTAINER="wimm-test-deb"
IMAGE="ubuntu:24.04"

die() {
    echo "test_deb: $*" >&2
    exit 1
}

read_version() {
    local version
    version="$(sed -n 's/^version = "\(.*\)"$/\1/p' "${ROOT}/pyproject.toml" | head -n 1)"
    [[ -n "${version}" ]] || die "cannot read version from pyproject.toml"
    printf '%s' "${version}"
}

cleanup() {
    # Only the fixed-name container of this script; never prune or touch anything else.
    docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true
}

# Runs inside the container as root. Arguments: deb path, expected version, app id, package.
# Quoted heredoc on purpose: the container shell expands it, not the host one.
INNER="$(cat <<'CONTAINER_SCRIPT'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
deb="$1"; version="$2"; app_id="$3"; pkg="$4"
fail() { echo "FAIL: $*" >&2; exit 1; }

# The ubuntu image excludes /usr/share/man and doc via dpkg, so the man page would never be
# unpacked and the file check below would test the image, not the package. Container only.
rm -f /etc/dpkg/dpkg.cfg.d/excludes
apt-get update -qq
apt-get install -y -qq "$deb" >/dev/null
echo "installed: $(dpkg-query -W -f="\${Package} \${Version}" "$pkg")"

files="
/usr/lib/python3/dist-packages/wimm/__init__.py
/usr/bin/wimm
/etc/xdg/autostart/${app_id}.desktop
/usr/share/applications/${app_id}.desktop
/usr/share/icons/hicolor/16x16/apps/${app_id}.png
/usr/share/icons/hicolor/48x48/apps/${app_id}.png
/usr/share/icons/hicolor/512x512/apps/${app_id}.png
/usr/share/icons/hicolor/scalable/status/wimm-normal.svg
/usr/share/icons/hicolor/scalable/status/wimm-warning.svg
/usr/share/icons/hicolor/scalable/status/wimm-critical.svg
/usr/share/metainfo/${app_id}.metainfo.xml
/usr/share/doc/${pkg}/copyright
/usr/share/man/man1/wimm.1.gz
"
for f in $files; do
    [ -e "$f" ] || fail "missing installed file: $f"
done
echo "files: all SPECIFICHE 12.2 paths present"

out="$(wimm --version)" || fail "wimm --version exited non zero"
echo "wimm --version: $out"
case "$out" in *"$version"*) ;; *) fail "version \"$version\" not in output" ;; esac

apt-get install -y -qq lintian >/dev/null
lint_rc=0
lintian --fail-on error "$deb" || lint_rc=$?
[ "$lint_rc" -eq 0 ] || fail "lintian reported errors (exit $lint_rc)"
echo "lintian: no errors"

apt-get remove -y -qq "$pkg" >/dev/null
left=""
for p in /usr/lib/python3/dist-packages/wimm /usr/bin/wimm \
    "/usr/share/applications/${app_id}.desktop"; do
    [ ! -e "$p" ] || left="$left $p"
done
[ -z "$left" ] || fail "left after remove:$left"
# The autostart file is a conffile (lintian error otherwise): dpkg keeps it on remove by
# design and drops it on purge. It may survive remove only in that state.
autostart="/etc/xdg/autostart/${app_id}.desktop"
if [ -e "$autostart" ]; then
    state="$(dpkg-query -W -f="\${db:Status-Abbrev}" "$pkg")"
    [ "$state" = "rc " ] || fail "autostart left after remove, package state \"$state\""
    echo "remove: only the conffile $autostart is kept (state rc)"
else
    echo "remove: nothing left behind"
fi
apt-get purge -y -qq "$pkg" >/dev/null
[ ! -e "$autostart" ] || fail "autostart left after purge"
echo "purge: autostart conffile gone"
CONTAINER_SCRIPT
)"

main() {
    command -v docker >/dev/null 2>&1 || die "docker not found"
    local version deb
    version="$(read_version)"
    deb="${ROOT}/dist/${PACKAGE}_${version}_all.deb"
    [[ -f "${deb}" ]] || die "missing ${deb}: run make deb first"

    cleanup
    trap cleanup EXIT
    docker run --rm --name "${CONTAINER}" \
        -v "${deb}:/pkg/${PACKAGE}.deb:ro" \
        "${IMAGE}" bash -c "${INNER}" _ "/pkg/${PACKAGE}.deb" "${version}" "${APP_ID}" "${PACKAGE}"
    echo "test_deb: OK (${version})"
}

main "$@"
