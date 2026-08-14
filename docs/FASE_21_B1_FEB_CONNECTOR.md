# FASE 21.B1 — FEB Source Connector

## Purpose

Connect the official FEB public competition pages to the existing `feb_score` command API without coupling the source scraper to the domain or persistence layers.

## Source flow

1. Read a FEB `resultados.aspx` competition/phase page.
2. Parse match id, teams, score, date/time and jornada.
3. Open the official match page.
4. Extract the per-match LiveStats bearer token embedded by FEB.
5. Use that token only for read-only LiveStats requests.
6. Resolve stable FEB team identifiers from the BoxScore when available.
7. Publish an idempotent `create_or_update_match` command to Production.
8. Keep source URLs as raw references so the domain remains the source-of-truth boundary.

The connector never logs the FEB LiveStats token or the production API key.

## Current scope

The existing v1 command contract stores match metadata and source references. The connector therefore does **not** silently inject score/player/team-stat payloads into the command. A dedicated statistics ingestion contract is still required before those normalized statistics can be persisted in the aggregate.

## Running locally

Install connector dependencies:

```bash
python3 -m pip install -r connectors/feb/requirements.txt
```

Set the raw Production API key (64-hex value only):

```bash
export FEB_SCORE_API_KEY='...'
export FEB_SCORE_API_URL='https://feb-score-api-production.up.railway.app'
```

Run a small production smoke ingest first:

```bash
python3 scripts/feb_ingest.py --limit 1
```

For a specific FEB phase/results page:

```bash
python3 scripts/feb_ingest.py --results-url 'https://baloncestoenvivo.feb.es/resultados.aspx?...' --limit 1
```

## Safety

- The connector uses the production API key only for the `feb_score` API.
- The FEB LiveStats token is extracted per match and used only against `intrafeb.feb.es`.
- Command ids are deterministic per match, so rerunning the same page is idempotent.
- Production deploy is not part of this connector script; deployment remains governed by the existing CI/CD workflow.
