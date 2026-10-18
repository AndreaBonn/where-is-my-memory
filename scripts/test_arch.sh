#!/usr/bin/env bash
# Build packaging/arch/PKGBUILD in a throwaway archlinux:latest container, install the result
# with pacman and run `wimm --version`. Source is `git archive HEAD` (committed state only),
# never a download. Touches nothing on the host except the container wimm-test-arch and a
# temporary directory, both removed on exit. Publishes nothing.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKAGE="where-is-my-memory"
CONTAINER="wimm-test-arch"
IMAGE="archlinux:latest"
WORK=""

die() {
    echo "test_arch: $*" >&2
    exit 1
}

read_version() {
    local version
    version="$(sed -n 's/^version = "\(.*\)"$/\1/p' "${ROOT}/pyproject.toml" | head -n 1)"
    [[ -n "${version}" ]] || die "cannot read version from pyproject.toml"
    printf '%s' "${version}"
}

cleanup() {
    docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true
    [[ -z "${WORK}" ]] || rm -rf "${WORK}"
}

# Runs inside the container as root. Argument: expected version. Quoted heredoc on purpose.
INNER="$(cat <<'CONTAINER_SCRIPT'
set -euo pipefail
version="$1"
fail() { echo "FAIL: $*" >&2; exit 1; }

# makepkg refuses root, and -s would need sudo: install the build tools (python is read by package()) as root, build as
# an unprivileged user.
pacman -Syu --noconfirm --needed gettext fakeroot binutils python >/dev/null
useradd --create-home builder
install -d -o builder -g builder /home/builder/pkg
cp /src/PKGBUILD /src/*.install /src/*.tar.gz /home/builder/pkg/
chown -R builder:builder /home/builder/pkg
runuser -u builder -- bash -c 'cd /home/builder/pkg && makepkg --nodeps --noprogressbar' \
    > /tmp/makepkg.log 2>&1 || { tail -n 40 /tmp/makepkg.log; fail "makepkg failed"; }
pkg="$(ls /home/builder/pkg/*.pkg.tar.* | head -n 1)"
echo "built: $(basename "$pkg")"

pacman -U --noconfirm "$pkg" >/tmp/pacman.log 2>&1 || { tail -n 30 /tmp/pacman.log; fail "pacman -U failed"; }
echo "installed: $(pacman -Q "$PKG_NAME")"
echo "--- installed files (pacman -Ql, files only)"
pacman -Ql "$PKG_NAME" | awk '{print $2}' | grep -v '/$' | sort

out="$(wimm --version)" || fail "wimm --version exited non zero"
echo "wimm --version: $out"
case "$out" in *"$version"*) ;; *) fail "version \"$version\" not in output" ;; esac

pacman -R --noconfirm "$PKG_NAME" >/dev/null
left="$(pacman -Ql "$PKG_NAME" 2>/dev/null || true)"
[ -z "$left" ] || fail "package still registered after remove"
[ ! -e /usr/bin/wimm ] || fail "/usr/bin/wimm left after remove"
# wimm --version ran as root and left __pycache__: pre_remove must have cleaned it.
! compgen -G "/usr/lib/python3*/site-packages/wimm" >/dev/null || fail "wimm package dir left"
echo "remove: ok"
CONTAINER_SCRIPT
)"

main() {
    command -v docker >/dev/null 2>&1 || die "docker not found"
    local version pkgver
    version="$(read_version)"
    pkgver="$(sed -n 's/^pkgver=\(.*\)$/\1/p' "${ROOT}/packaging/arch/PKGBUILD")"
    [[ "${pkgver}" == "${version}" ]] || die "PKGBUILD pkgver ${pkgver} != pyproject version ${version}"

    if [[ -n "$(git -C "${ROOT}" status --porcelain)" ]]; then
        echo "warning: uncommitted changes are not in the package (built from git archive HEAD)" >&2
    fi
    WORK="$(mktemp -d)"
    # mktemp makes it 0700 for the host user; the unprivileged builder in the container reads it.
    chmod 755 "${WORK}"
    trap cleanup EXIT
    cp "${ROOT}/packaging/arch/"* "${WORK}/"
    git -C "${ROOT}" archive --format=tar.gz --prefix="${PACKAGE}-${version}/" \
        -o "${WORK}/${PACKAGE}-${version}.tar.gz" HEAD
    docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true
    docker run --rm --name "${CONTAINER}" -e "PKG_NAME=${PACKAGE}" \
        -v "${WORK}:/src:ro" "${IMAGE}" bash -c "${INNER}" _ "${version}"
    echo "test_arch: OK (${version})"
}

main "$@"
