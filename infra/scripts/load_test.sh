#!/usr/bin/env bash
set -euo pipefail

PROFILE_FILE="${1:-tests/load/profiles.json}"
OUTPUT_DIR="${2:-artifacts/load}"

uv run python -m tests.load.runner --profiles "${PROFILE_FILE}" --output-dir "${OUTPUT_DIR}"
