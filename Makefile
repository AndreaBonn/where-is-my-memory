.PHONY: setup test test-all lint run deb

# Enforce core coverage only once executable core code exists.
CORE_HAS_CODE := $(shell test ! -d src/wimm/core || \
	find src/wimm/core -type f -name '*.py' \
	-exec grep -lE '^[[:space:]]*[^#[:space:]]' {} + 2>/dev/null)
CORE_COVERAGE := $(if $(strip $(CORE_HAS_CODE)),--cov=src/wimm/core --cov-fail-under=90)

setup:
	uv venv --system-site-packages --python /usr/bin/python3
	uv sync

test:
	uv run pytest -m "not integration and not ui and not dbus" $(CORE_COVERAGE)

test-all:
	dbus-run-session -- xvfb-run -a uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy src

run:
	@test -f scripts/dev_run.sh || { echo 'Missing script: scripts/dev_run.sh' >&2; exit 2; }
	scripts/dev_run.sh

deb:
	@test -f scripts/build_deb.sh || { echo 'Missing script: scripts/build_deb.sh' >&2; exit 2; }
	scripts/build_deb.sh
