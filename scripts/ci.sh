#!/usr/bin/env bash
# FASE 15 §12 — Reproducible local CI pipeline (no manual environment setup).
#
# Runs: install -> pip check -> full suite (unit/integration/API/production/
# architecture/PostgreSQL) -> deployment-artifact guards.
#
# PostgreSQL (optional): set FEB_SCORE_PG_DSN to a reachable server to also run
# the PostgreSQL-backed tests; without it those tests skip gracefully.
#
# Usage:  bash scripts/ci.sh
set -euo pipefail

VENV="${VENV:-.venv}"
PY="${PY:-$VENV/bin/python}"

echo "==> install"
if [ ! -x "$PY" ]; then
  python3 -m venv "$VENV"
fi
"$PY" -m pip install --upgrade pip
"$PY" -m pip install -r requirements.txt -r requirements-dev.txt

echo "==> pip check"
"$PY" -m pip check

echo "==> deployment artifact guards (static, no Docker needed)"
"$PY" -m pytest -q tests/production/test_deployment_artifacts.py

echo "==> full test suite (FEB_SCORE_PG_DSN=${FEB_SCORE_PG_DSN:-<unset: PG tests skip>})"
"$PY" -m pytest -q

echo "==> CI pipeline OK"
