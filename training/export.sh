#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
OUTPUT="${1:-exports/model-$(date +%Y%m%d-%H%M%S).zip}"
exec .venv/bin/python -B cloud_run.py export --output "$OUTPUT"
