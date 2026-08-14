# FEB Source Connector

Read-only fetch -> normalize -> submit `create_or_update_match` command.
Minimal-change: does NOT modify domain / API / staging / production variables.
Idempotent via deterministic `command_id` (UUIDv5 over `season_code|competition_id|external_id`).

## Run (local/offline-first dev)

Source fixture (no network):

```bash
export FEB_SOURCE_URL="file://$(pwd)/contracts/examples/feb_source_match_2513600.json"
export FEB_TARGET_API="http://localhost:8000"
export FEB_API_KEY="<64-hex staging key or empty for dry-run>"
python scripts/feb/ingest_match.py
```

No network? dry-run the command payload (no HTTP) by stubbing `post_command`.

## Production ingest (single match, real source)

```bash
export FEB_SOURCE_URL="https://<feb-source>/match/2513600.json"
export FEB_TARGET_API="https://feb-score-api-production.up.railway.app"
export FEB_API_KEY="<production 64-hex raw key from Railway var>"
export FEB_COMPETITION_ID="segunda-feb"   # optional
python scripts/feb/ingest_match.py
```

## Rules

- Never print `FEB_API_KEY` or any Railway token.
- `external_id` determinista: se preserva el de FEB (`payload.external_id`).
- Re-ingestar la misma `external_id` produce el mismo `command_id` → idempotency del server (command_id dedup outbox + domain).
- No toca staging ni production si no se apunta a `FEB_TARGET_API` real.
