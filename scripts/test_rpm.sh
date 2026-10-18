#!/usr/bin/env bash
# Build packaging/rpm/wimm.spec in a throwaway fedora:latest container, install the rpm with
# dnf and run `wimm --version`. Source is `git archive HEAD` (committed state only), never a
# download. Touches nothing on the host except the container wimm-test-rpm and a temporary
# directory, both removed on exit. Publishes nothing.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKAGE="where-is-my-memory"
CONTAINER="wimm-test-rpm"
IMAGE="fedora:latest"
WORK=""

die() {
    echo "test_rpm: $*" >&2
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

# The fedora image excludes man pages and docs through tsflags; the check below would test
# the image, not the package. Container only.
sed -i '/^tsflags=/d' /etc/dnf/dnf.conf 2>/dev/null || true
dnf install -y -q rpm-build gettext python3-devel >/tmp/dnf-build.log 2>&1 \
    || { tail -n 30 /tmp/dnf-build.log; fail "cannot install build tools"; }
useradd --create-home builder
runuser -u builder -- bash -c '
    set -e
    mkdir -p ~/rpmbuild/SOURCES ~/rpmbuild/SPECS
    cp /src/*.tar.gz ~/rpmbuild/SOURCES/
    cp /src/wimm.spec ~/rpmbuild/SPECS/
    rpmbuild -bb --nocheck ~/rpmbuild/SPECS/wimm.spec
' >/tmp/rpmbuild.log 2>&1 || { tail -n 40 /tmp/rpmbuild.log; fail "rpmbuild failed"; }
rpm_file="$(ls /home/builder/rpmbuild/RPMS/noarch/*.rpm | head -n 1)"
echo "built: $(basename "$rpm_file")"
echo "requires: $(rpm -qp --requires "$rpm_file" | grep -v '^rpmlib' | tr '\n' ';')"

dnf install -y -q "$rpm_file" >/tmp/dnf-install.log 2>&1 \
    || { tail -n 30 /tmp/dnf-install.log; fail "dnf install failed"; }
echo "installed: $(rpm -q "$PKG_NAME")"
echo "--- installed files (rpm -ql, files only)"
rpm -ql "$PKG_NAME" | while read -r p; do [ -d "$p" ] || echo "$p"; done | sort

out="$(wimm --version)" || fail "wimm --version exited non zero"
echo "wimm --version: $out"
case "$out" in *"$version"*) ;; *) fail "version \"$version\" not in output" ;; esac

dnf remove -y -q "$PKG_NAME" >/dev/null 2>&1
rpm -q "$PKG_NAME" >/dev/null 2>&1 && fail "package still installed after remove"
[ ! -e /usr/bin/wimm ] || fail "/usr/bin/wimm left after remove"
! compgen -G "/usr/lib/python3*/site-packages/wimm" >/dev/null || fail "wimm package dir left"
echo "remove: ok"
CONTAINER_SCRIPT
)"

main() {
    command -v docker >/dev/null 2>&1 || die "docker not found"
    local version specver
    version="$(read_version)"
    specver="$(sed -n 's/^Version:[[:space:]]*\(.*\)$/\1/p' "${ROOT}/packaging/rpm/wimm.spec")"
    [[ "${specver}" == "${version}" ]] || die "spec Version ${specver} != pyproject version ${version}"

    if [[ -n "$(git -C "${ROOT}" status --porcelain)" ]]; then
        echo "warning: uncommitted changes are not in the package (built from git archive HEAD)" >&2
    fi
    WORK="$(mktemp -d)"
    # mktemp makes it 0700 for the host user; the unprivileged builder in the container reads it.
    chmod 755 "${WORK}"
    trap cleanup EXIT
    cp "${ROOT}/packaging/rpm/wimm.spec" "${WORK}/"
    git -C "${ROOT}" archive --format=tar.gz --prefix="${PACKAGE}-${version}/" \
        -o "${WORK}/${PACKAGE}-${version}.tar.gz" HEAD
    docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true
    docker run --rm --name "${CONTAINER}" -e "PKG_NAME=${PACKAGE}" \
        -v "${WORK}:/src:ro" "${IMAGE}" bash -c "${INNER}" _ "${version}"
    echo "test_rpm: OK (${version})"
}

main "$@"
