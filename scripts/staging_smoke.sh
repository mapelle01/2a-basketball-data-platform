#!/usr/bin/env bash
# FASE 18.1 — Real smoke test against a LIVE staging deployment.
#
# Usage:
#   bash scripts/staging_smoke.sh <base_url> <api_key>
#
# No secrets are hardcoded: the API key comes from the argument / environment.
# The script exits non-zero on the first failed check.
#
# Checks:
#   1. GET  /health                                  -> {"status":"ok"}
#   2. GET  /ready                                   -> {"status":"ready"}
#   3. POST /v1/commands/create_or_update_match      -> 200, accepted, event match_upserted
#   4. GET  /v1/matches/<external_id>                -> 200 with the created match
set -euo pipefail

BASE_URL="${1:?usage: staging_smoke.sh <base_url> <api_key>}"
API_KEY="${2:?usage: staging_smoke.sh <base_url> <api_key>}"
EXT="smoke-$(date +%s)"

echo "==> [1/4] GET ${BASE_URL}/health"
curl -fsS "${BASE_URL}/health" | grep -q '"status": *"ok"'

echo "==> [2/4] GET ${BASE_URL}/ready"
curl -fsS "${BASE_URL}/ready" | grep -q '"status": *"ready"'

echo "==> [3/4] POST ${BASE_URL}/v1/commands/create_or_update_match (external_id=${EXT})"
post=$(curl -sS -w '\nHTTP %{http_code}' -X POST "${BASE_URL}/v1/commands/create_or_update_match" \
  -H "Authorization: Bearer ${API_KEY}" \
  -H 'Content-Type: application/json' \
  -d "{\"payload\":{\"external_id\":\"${EXT}\",\"competition_id\":\"smoke-comp\",\"season_code\":\"2025-2026\",\"round_number\":1,\"scheduled_at\":\"2026-02-01T18:30:00Z\",\"home_team\":{\"external_id\":\"smoke-home\",\"name\":\"Home\"},\"away_team\":{\"external_id\":\"smoke-away\",\"name\":\"Away\"},\"source\":{\"id\":\"staging-smoke\",\"fetched_at\":\"2026-02-01T18:00:00Z\",\"s3_path\":\"s3://smoke\"}}}")
printf '%s\n' "$post"
code=$(printf '%s\n' "$post" | tail -n1 | awk '{print $2}')
[ "$code" = "200" ] || { echo "FAIL: expected HTTP 200, got $code" >&2; exit 1; }
printf '%s\n' "$post" | sed '$d' | grep -q '"status": *"accepted"' || { echo "FAIL: command not accepted" >&2; exit 1; }
printf '%s\n' "$post" | sed '$d' | grep -q '"event_type": *"match_upserted"' || { echo "FAIL: expected event match_upserted" >&2; exit 1; }

echo "==> [4/4] GET ${BASE_URL}/v1/matches/${EXT}"
curl -fsS "${BASE_URL}/v1/matches/${EXT}" | grep -q "\"external_id\": *\"${EXT}\""

echo "==> STAGING SMOKE OK"
