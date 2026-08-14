"""FASE 21.B1 — connector unit tests (offline, no network, no prod/staging).

Valida: normalize -> command envelope, deterministic command_id (idempotency),
external_id preserved, actor role=system, schema field conformance, error
handling (missing env / bad source shape). Does NOT hit any API.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "feb"))
import ingest_match as M

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((ROOT / "contracts" / "examples" / "feb_source_match_2513600.json").read_text())


def _cmd():
    return M.to_command(FIXTURE, "segunda-feb")


def test_command_envelope_shape():
    c = _cmd()
    assert set(c) == {"command_id", "meta", "actor", "payload"}
    assert c["meta"]["version"] == "1.0"
    assert c["actor"] == {"id": "ingestor-1", "role": "system"}


def test_command_id_is_deterministic_and_uuidv5():
    c1 = _cmd()["command_id"]
    c2 = _cmd()["command_id"]
    assert c1 == c2
    assert uuid.UUID(c1).version == 5


def test_command_id_differs_across_season_or_external_id():
    base = FIXTURE["payload"]
    a = M.to_command(FIXTURE, "segunda-feb")["command_id"]
    other = json.loads(json.dumps(FIXTURE))
    other["payload"]["external_id"] = "9999999"
    other["payload"]["season_code"] = "2026-2027"
    b = M.to_command(other, "segunda-feb")["command_id"]
    assert a != b


def test_external_id_preserved_from_source():
    c = _cmd()
    assert c["payload"]["external_id"] == FIXTURE["payload"]["external_id"]


def test_season_round_scheduled_preserved():
    c = _cmd()
    p = c["payload"]
    assert p["season_code"] == "2025-2026"
    assert p["round_number"] == 5
    assert p["scheduled_at"] == FIXTURE["payload"]["scheduled_at"]


def test_team_refs_preserved():
    c = _cmd()
    assert c["payload"]["home_team"] == FIXTURE["payload"]["home_team"]
    assert c["payload"]["away_team"] == FIXTURE["payload"]["away_team"]


def test_source_s3_path_fallback_when_missing():
    raw = json.loads(json.dumps(FIXTURE))
    raw["source"] = "feb-api"
    raw["fetched_at"] = "2026-02-01T20:00:00Z"
    raw["payload"]["raw"] = {}
    c = M.to_command(raw, "segunda-feb")
    ext = c["payload"]["external_id"]
    assert c["payload"]["source"]["s3_path"] == f"s3://raw/{ext}_boxscore.json"


def test_missing_required_env_returns_config_error():
    # run() returns exit code 2 + prints CONFIG_ERROR when a required env var is missing.
    saved = {k: os.environ.pop(k, None) for k in
             ("FEB_SOURCE_URL", "FEB_TARGET_API", "FEB_API_KEY")}
    try:
        rc = M.run()
        assert rc == 2
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def test_to_command_rejects_bad_shape():
    bad = {"payload": {}}  # missing external_id/season_code
    with pytest.raises(KeyError):
        M.to_command(bad, "segunda-feb")
