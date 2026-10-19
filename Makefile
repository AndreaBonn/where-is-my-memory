.PHONY: setup test test-all perf lint audit run deb test-deb test-arch test-rpm pot po mo

# Enforce core coverage only once executable core code exists.
CORE_HAS_CODE := $(shell test ! -d src/wimm/core || \
	find src/wimm/core -type f -name '*.py' \
	-exec grep -lE '^[[:space:]]*[^#[:space:]]' {} + 2>/dev/null)
CORE_COVERAGE := $(if $(strip $(CORE_HAS_CODE)),--cov=src/wimm/core --cov-fail-under=90)

# The msgid is the Italian source text: only the English catalog exists (wimm.i18n).
XGETTEXT_FLAGS := --from-code=UTF-8 --language=Python --keyword=N_ --keyword=pgettext:1c,2 \
	--add-comments=TRANSLATORS: \
	--package-name=where-is-my-memory --sort-by-file --force-po
PO_TEMPLATE := build/po/wimm.pot
MO_FILE := src/wimm/locale/en/LC_MESSAGES/wimm.mo

setup:
	uv venv --system-site-packages --python /usr/bin/python3
	uv sync

test:
	uv run pytest -m "not integration and not ui and not dbus" $(CORE_COVERAGE)

test-all:
	# tests/private_session.py gives every run its own display and session bus.
	uv run pytest

perf:
	# Same renderer the app sets for itself in wimm.app.GRAPHICS_DEFAULTS.
	GSK_RENDERER=cairo GDK_DEBUG=gl-disable,vulkan-disable uv run pytest -m perf -s

lint:
	# No cache: a stale .ruff_cache once hid an import-order error that a clean clone caught.
	uv run ruff check --no-cache .
	uv run ruff format --no-cache --check .
	uv run mypy src tests
	# Every user-visible string goes through gettext and po/en.po covers them all.
	uv run python scripts/check_i18n.py

# Isolated tool environments: installed in the venv, pip-audit's requests 2.34 shadowed the
# apt one and broke python3-docker 5.0.3 (tests/test_lockfile.py).
BANDIT := bandit@1.9.4
PIP_AUDIT := pip-audit@2.10.1

# Security scan. The runtime has no PyPI dependencies (psutil, docker and PyGObject come
# from apt), so pip-audit covers the development group exported by uv. The export is fully
# pinned, so pip-audit skips its own resolution (--no-deps --disable-pip): resolving would
# build PyGObject, which only exists as a stub dependency here.
audit:
	uvx $(BANDIT) -c pyproject.toml -r src -q
	@req="$$(mktemp)" && trap 'rm -f "$$req"' EXIT && \
		uv export --no-hashes --no-emit-project > "$$req" && \
		uvx $(PIP_AUDIT) --no-deps --disable-pip -r "$$req"

# Extract every marked string into the (unversioned) template.
pot:
	mkdir -p $(dir $(PO_TEMPLATE))
	xgettext $(XGETTEXT_FLAGS) -o $(PO_TEMPLATE) $$(git ls-files --cached --others \
		--exclude-standard 'src/wimm/*.py')

# Add new strings to po/en.po and drop the ones no longer in the code. The creation date
# is dropped too: it would change the catalog on every run without a new string.
po: pot
	msgmerge --quiet --update --backup=none --no-fuzzy-matching --no-wrap po/en.po $(PO_TEMPLATE)
	msgattrib --no-obsolete --no-wrap -o po/en.po po/en.po
	sed -i '/^"POT-Creation-Date:/d' po/en.po

mo:
	mkdir -p $(dir $(MO_FILE))
	msgfmt --check-format --check-domain -o $(MO_FILE) po/en.po

run: mo
	@test -f scripts/dev_run.sh || { echo 'Missing script: scripts/dev_run.sh' >&2; exit 2; }
	scripts/dev_run.sh

deb:
	@test -f scripts/build_deb.sh || { echo 'Missing script: scripts/build_deb.sh' >&2; exit 2; }
	scripts/build_deb.sh

test-deb:
	@test -f scripts/test_deb.sh || { echo 'Missing script: scripts/test_deb.sh' >&2; exit 2; }
	scripts/test_deb.sh

test-arch:
	@test -f scripts/test_arch.sh || { echo 'Missing script: scripts/test_arch.sh' >&2; exit 2; }
	scripts/test_arch.sh

test-rpm:
	@test -f scripts/test_rpm.sh || { echo 'Missing script: scripts/test_rpm.sh' >&2; exit 2; }
	scripts/test_rpm.sh
