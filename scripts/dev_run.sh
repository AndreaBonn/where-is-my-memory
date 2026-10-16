#!/usr/bin/env bash
set -euo pipefail
WIMM_APP_ID=io.github.wimm.WhereIsMyMemory.Devel exec uv run wimm "$@"
