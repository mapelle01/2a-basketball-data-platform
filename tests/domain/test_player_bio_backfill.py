"""Player bio enrichment: fill what's empty, never overwrite what exists."""
from __future__ import annotations

from datetime import date

from feb_score.application.use_cases.player_bio_backfill import (
    PlayerBioBackfillService,
    PublicProfileBioResolver,
)
from feb_score.domain.player.model import Player
import uuid

from feb_score.domain.value_objects import ExternalId, PlayerId, SeasonCode

SEASON = SeasonCode("2024-2025")
BIO = {"position": "Alero", "height_cm": 196, "birth_date": date(1998, 4, 11),
       "birth_place": "Barcelona", "nationality": "ESPAÑA"}


class _Agg:
    def __init__(self, pid):
        self.player_external_id = pid


class _Stats:
    def __init__(self, ids, teams=None):
        self._ids = ids
        self._teams = teams or {}

    def list_season_player_aggregates(self, season):
        return [_Agg(i) for i in self._ids]

    def list_player_season_teams(self, pid, season):
        return self._teams.get(pid, [])


class _Players:
    def __init__(self, players):
        self._by_id = {str(p.external_id): p for p in players}
        self.saved = []

    def get_by_external_id(self, external_id):
        return self._by_id.get(str(external_id))

    def save(self, player):
        self.saved.append(player)


def _player(pid="p1", name="X", **kw):
    return Player(external_id=ExternalId(pid), player_id=PlayerId(str(uuid.uuid4())),
                  name=name, **kw)


class _Resolver:
    def __init__(self, mapping):
        self._m = mapping

    def resolve(self, pid):
        return self._m.get(pid)


def test_fills_empty_bio_fields():
    p = _player()
    repo = _Players([p])
    stats = PlayerBioBackfillService(repo, _Stats(["p1"]), _Resolver({"p1": BIO})).run(SEASON)
    assert (stats.seen, stats.updated, stats.unchanged) == (1, 1, 0)
    assert p.height_cm == 196 and p.nationality == "ESPAÑA"
    assert p.birth_date == date(1998, 4, 11) and p.birth_place == "Barcelona"
    assert repo.saved == [p]


def test_never_overwrites_an_existing_value():
    """A human correction in the platform must survive every later backfill."""
    p = _player(nationality="ANDORRA", height_cm=201)
    repo = _Players([p])
    PlayerBioBackfillService(repo, _Stats(["p1"]), _Resolver({"p1": BIO})).run(SEASON)
    assert p.nationality == "ANDORRA" and p.height_cm == 201
    assert p.position == "Alero"  # the empty ones still get filled


def test_rerun_writes_nothing():
    p = _player(**BIO)
    repo = _Players([p])
    stats = PlayerBioBackfillService(repo, _Stats(["p1"]), _Resolver({"p1": BIO})).run(SEASON)
    assert (stats.updated, stats.unchanged) == (0, 1)
    assert repo.saved == []


def test_dry_run_changes_nothing_in_the_repo():
    p = _player()
    repo = _Players([p])
    stats = PlayerBioBackfillService(repo, _Stats(["p1"]),
                                     _Resolver({"p1": BIO})).run(SEASON, dry_run=True)
    assert stats.updated == 1 and repo.saved == []


def test_unresolved_and_missing_players_are_counted_not_fatal():
    repo = _Players([_player("p1")])
    stats = PlayerBioBackfillService(
        repo, _Stats(["p1", "p2"]), _Resolver({"p1": None})).run(SEASON)
    assert stats.seen == 2 and stats.unresolved == 2 and stats.errors == 0


def test_resolver_skips_players_without_a_known_team():
    """The profile URL needs both ids; with no team there is nothing to fetch."""
    r = PublicProfileBioResolver(_Stats(["p1"], teams={}), "2024-2025",
                                 fetch=lambda p, t: "", parse=lambda h, p: None)
    assert r.resolve("p1") is None


def test_resolver_isolates_a_failing_profile():
    def boom(pid, tid):
        raise RuntimeError("unreachable")

    r = PublicProfileBioResolver(_Stats(["p1"], teams={"p1": ["t1"]}), "2024-2025",
                                 fetch=boom, parse=lambda h, p: None)
    assert r.resolve("p1") is None


def test_profile_name_upgrades_an_abbreviated_one():
    """The boxscore often gives only an initial; the profile has the full given
    name, and that is strictly more information — so it upgrades."""
    p = _player(name="J. JUANOLA MADERA")
    repo = _Players([p])
    bio = {**BIO, "name": "JUANOLA MADERA, JORDI"}
    PlayerBioBackfillService(repo, _Stats(["p1"]), _Resolver({"p1": bio})).run(SEASON)
    assert p.name == "JUANOLA MADERA, JORDI"


def test_a_complete_name_is_never_churned():
    p = _player(name="SAMAR, MATIJA")
    repo = _Players([p])
    bio = {**BIO, "name": "OTRO, NOMBRE"}
    PlayerBioBackfillService(repo, _Stats(["p1"]), _Resolver({"p1": bio})).run(SEASON)
    assert p.name == "SAMAR, MATIJA"
