.PHONY: setup test test-all perf lint run deb test-deb pot po mo

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
	dbus-run-session -- xvfb-run -a uv run pytest

perf:
	# Same renderer the app sets for itself in wimm.app.GRAPHICS_DEFAULTS.
	GSK_RENDERER=cairo GDK_DEBUG=gl-disable,vulkan-disable xvfb-run -a uv run pytest -m perf -s

lint:
	# No cache: a stale .ruff_cache once hid an import-order error that a clean clone caught.
	uv run ruff check --no-cache .
	uv run ruff format --no-cache --check .
	uv run mypy src tests
	# Every user-visible string goes through gettext and po/en.po covers them all.
	uv run python scripts/check_i18n.py

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
