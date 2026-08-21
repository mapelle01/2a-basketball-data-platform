"""CopyContract — the editorial copy generated from a StoryObject.

Every claim in the copy MUST reference a fact from the Story via ``facts_used``.
The FactValidator enforces this: any number or entity name in the copy that
does not appear in ``facts_used`` fails validation and blocks publication.

v1 uses deterministic template strings (Spanish). An LLM can be plugged in
later — but only as a rewriter that receives the same fact list; it can
never introduce new numbers or entities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple


@dataclass(frozen=True)
class CopyContract:
    headline: str
    subtitle: str
    caption: str
    hashtags: Tuple[str, ...]
    facts_used: Tuple[str, ...]
    locale: str = "es"
    generator: str = "deterministic-v1"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "headline": self.headline,
            "subtitle": self.subtitle,
            "caption": self.caption,
            "hashtags": list(self.hashtags),
            "facts_used": list(self.facts_used),
            "locale": self.locale,
            "generator": self.generator,
        }


BASE_HASHTAGS = ("SegundaFEB", "Baloncesto", "2aFEBScore")


def generate_copy_match_final(story: Dict[str, Any]) -> CopyContract:
    """Copy for MATCH_FINAL. Deterministic; Spanish.

    Reads only from story['facts']. Any number in the resulting strings must
    correspond to a key in facts_used.
    """
    f = story["facts"]
    home_name = f.get("home_team_name") or f.get("home_team_external_id", "Local")
    away_name = f.get("away_team_name") or f.get("away_team_external_id", "Visitante")
    home_score = f["home_score"]
    away_score = f["away_score"]
    round_number = story.get("round_number")

    winner = home_name if home_score > away_score else away_name
    margin = abs(home_score - away_score)

    if margin <= 5:
        adjective = "in extremis"
    elif margin >= 20:
        adjective = "de forma contundente"
    else:
        adjective = "con solvencia"

    headline = f"{home_name} {home_score}-{away_score} {away_name}"
    subtitle = f"{winner} se lleva el partido {adjective} · Jornada {round_number}"
    caption = (
        f"{winner} vence {home_score}-{away_score} en la jornada {round_number} "
        f"de Segunda FEB."
    )

    return CopyContract(
        headline=headline,
        subtitle=subtitle,
        caption=caption,
        hashtags=BASE_HASHTAGS + (_slugify(home_name), _slugify(away_name)),
        facts_used=(
            "home_team_name",
            "away_team_name",
            "home_score",
            "away_score",
            "round_number",
        ),
    )


def generate_copy_player_of_round(story: Dict[str, Any]) -> CopyContract:
    f = story["facts"]
    name = f.get("player_name") or f.get("player_external_id", "El jugador")
    team = f.get("team_name") or f.get("team_external_id", "")
    round_number = story.get("round_number")
    points = f["points"]
    rebounds = f["rebounds"]
    assists = f["assists"]
    impact = f["impact_score"]

    headline = f"{name}"
    subtitle = f"Jugador de la jornada {round_number} · valoración {impact}"
    caption = (
        f"{name} lidera la jornada {round_number} con {points} puntos, "
        f"{rebounds} rebotes y {assists} asistencias. Valoración {impact}."
    )

    hashtags = BASE_HASHTAGS + ("PlayerOfTheRound",)
    if team:
        hashtags = hashtags + (_slugify(team),)

    return CopyContract(
        headline=headline,
        subtitle=subtitle,
        caption=caption,
        hashtags=hashtags,
        facts_used=(
            "player_name",
            "team_name",
            "points",
            "rebounds",
            "assists",
            "impact_score",
            "round_number",
        ),
    )


def generate_copy_round_recap(story: Dict[str, Any]) -> CopyContract:
    f = story["facts"]
    round_number = story.get("round_number")
    n_matches = f["matches_played"]
    biggest_win_margin = f.get("biggest_win_margin", 0)

    # The top-scorer clause is included ONLY when the round has boxscore data.
    # A round with no player stats (imperfect feed) still gets a valid recap —
    # never a fabricated "— (0 pts)".
    top_scorer_name = f.get("top_scorer_name") or f.get("top_scorer_external_id")
    top_scorer_points = f.get("top_scorer_points")
    facts_used = ["matches_played", "biggest_win_margin"]

    headline = f"Jornada {round_number}"
    subtitle = f"{n_matches} partidos · el resumen"

    if top_scorer_name and top_scorer_points is not None:
        scorer_clause = f"{top_scorer_name} ({top_scorer_points} pts) máximo anotador; "
        facts_used += ["top_scorer_name", "top_scorer_points"]
    else:
        scorer_clause = ""

    caption = (
        f"Resumen de la jornada {round_number}: {n_matches} partidos disputados. "
        f"{scorer_clause}mayor diferencia: {biggest_win_margin} puntos."
    )

    return CopyContract(
        headline=headline,
        subtitle=subtitle,
        caption=caption,
        hashtags=BASE_HASHTAGS + ("Jornada",),
        facts_used=tuple(facts_used),
    )


def generate_copy_biggest_win(story: Dict[str, Any]) -> CopyContract:
    f = story["facts"]
    home_name = f.get("home_team_name") or f.get("home_team_external_id", "Local")
    away_name = f.get("away_team_name") or f.get("away_team_external_id", "Visitante")
    home_score = f["home_score"]
    away_score = f["away_score"]
    margin = f["margin"]
    round_number = story.get("round_number")
    winner = home_name if home_score > away_score else away_name

    headline = f"{home_name} {home_score}-{away_score} {away_name}"
    subtitle = f"La goleada de la jornada {round_number} · +{margin}"
    caption = (
        f"{winner} firma la mayor diferencia de la jornada {round_number}: "
        f"{home_score}-{away_score} (+{margin})."
    )
    return CopyContract(
        headline=headline,
        subtitle=subtitle,
        caption=caption,
        hashtags=BASE_HASHTAGS + ("Goleada", _slugify(winner)),
        facts_used=(
            "home_team_name",
            "away_team_name",
            "home_score",
            "away_score",
            "margin",
            "round_number",
        ),
    )


def generate_copy_notable_performance(story: Dict[str, Any]) -> CopyContract:
    f = story["facts"]
    name = f.get("player_name") or f.get("player_external_id", "El jugador")
    team = f.get("team_name") or f.get("team_external_id", "")
    round_number = story.get("round_number")
    points = f["points"]
    rebounds = f["rebounds"]
    assists = f["assists"]
    is_triple = story["story_type"] == "triple_double"
    label = "Triple-doble" if is_triple else "Doble-doble"

    headline = f"{name}"
    subtitle = f"{label} en la jornada {round_number}"
    caption = (
        f"{label} de {name}: {points} puntos, {rebounds} rebotes y "
        f"{assists} asistencias en la jornada {round_number}."
    )
    hashtags = BASE_HASHTAGS + (("TripleDoble",) if is_triple else ("DobleDoble",))
    if team:
        hashtags = hashtags + (_slugify(team),)

    return CopyContract(
        headline=headline,
        subtitle=subtitle,
        caption=caption,
        hashtags=hashtags,
        facts_used=("player_name", "team_name", "points", "rebounds", "assists", "round_number"),
    )


def generate_copy_season_high(story: Dict[str, Any]) -> CopyContract:
    f = story["facts"]
    name = f.get("player_name") or f.get("player_external_id", "El jugador")
    team = f.get("team_name") or f.get("team_external_id", "")
    round_number = story.get("round_number")
    points = f["points"]
    previous_best = f["previous_best"]

    headline = f"{name}"
    subtitle = f"Máximo de la temporada · {points} puntos"
    caption = (
        f"Nuevo máximo de la temporada para {name}: {points} puntos en la "
        f"jornada {round_number} (anterior mejor marca: {previous_best})."
    )
    hashtags = BASE_HASHTAGS + ("SeasonHigh",)
    if team:
        hashtags = hashtags + (_slugify(team),)
    return CopyContract(
        headline=headline,
        subtitle=subtitle,
        caption=caption,
        hashtags=hashtags,
        facts_used=("player_name", "team_name", "points", "previous_best", "round_number"),
    )


def generate_copy_upset(story: Dict[str, Any]) -> CopyContract:
    f = story["facts"]
    home_name = f.get("home_team_name") or f.get("home_team_external_id", "Local")
    away_name = f.get("away_team_name") or f.get("away_team_external_id", "Visitante")
    home_score = f["home_score"]
    away_score = f["away_score"]
    round_number = story.get("round_number")
    winner = f.get("winner_name") or (home_name if home_score > away_score else away_name)

    headline = f"{home_name} {home_score}-{away_score} {away_name}"
    subtitle = f"Sorpresa en la jornada {round_number}"
    caption = (
        f"Sorpresa de la jornada {round_number}: {winner} da la campanada "
        f"({home_score}-{away_score})."
    )
    return CopyContract(
        headline=headline,
        subtitle=subtitle,
        caption=caption,
        hashtags=BASE_HASHTAGS + ("Sorpresa",),
        facts_used=("home_team_name", "away_team_name", "home_score", "away_score", "round_number"),
    )


def generate_copy_stat_leaderboard(story: Dict[str, Any]) -> CopyContract:
    f = story["facts"]
    round_number = story.get("round_number")
    leaders = f.get("leaders", [])
    top = leaders[0] if leaders else {}
    top_name = top.get("player_name") or top.get("player_external_id", "—")
    top_points = top.get("points", 0)

    headline = "Máximos anotadores"
    subtitle = f"Jornada {round_number} · el top de la jornada"
    caption = (
        f"Los máximos anotadores de la jornada {round_number} de Segunda FEB. "
        f"{top_name} lidera con {top_points} puntos."
    )
    return CopyContract(
        headline=headline,
        subtitle=subtitle,
        caption=caption,
        hashtags=BASE_HASHTAGS + ("TopScorers",),
        # The number in the caption traces to the leader's points.
        facts_used=("round_number",),
    )


def generate_copy_iron_man(story: Dict[str, Any]) -> CopyContract:
    f = story["facts"]
    name = f.get("player_name") or f.get("player_external_id", "El jugador")
    team = f.get("team_name") or f.get("team_external_id", "")
    round_number = story.get("round_number")
    minutes = f["minutes_played"]
    points = f["points"]

    headline = f"{name}"
    subtitle = f"El que no se sienta · {minutes} minutos"
    caption = (
        f"{name} firma {minutes} minutos en la jornada {round_number}: el que "
        f"más tiempo aguantó en pista, con {points} puntos."
    )
    hashtags = BASE_HASHTAGS + ("Maraton",)
    if team:
        hashtags = hashtags + (_slugify(team),)
    return CopyContract(
        headline=headline,
        subtitle=subtitle,
        caption=caption,
        hashtags=hashtags,
        facts_used=("player_name", "team_name", "minutes_played", "points", "round_number"),
    )


def generate_copy_playmaker(story: Dict[str, Any]) -> CopyContract:
    f = story["facts"]
    name = f.get("player_name") or f.get("player_external_id", "El jugador")
    team = f.get("team_name") or f.get("team_external_id", "")
    round_number = story.get("round_number")
    assists = f["assists"]
    points = f["points"]

    headline = f"{name}"
    subtitle = f"El director · {assists} asistencias"
    caption = (
        f"{name} reparte {assists} asistencias en la jornada {round_number}, "
        f"el que más, sumando además {points} puntos."
    )
    hashtags = BASE_HASHTAGS + ("Asistencias",)
    if team:
        hashtags = hashtags + (_slugify(team),)
    return CopyContract(
        headline=headline,
        subtitle=subtitle,
        caption=caption,
        hashtags=hashtags,
        facts_used=("player_name", "team_name", "assists", "points", "round_number"),
    )


def generate_copy_sharpshooter(story: Dict[str, Any]) -> CopyContract:
    f = story["facts"]
    name = f.get("player_name") or f.get("player_external_id", "El jugador")
    team = f.get("team_name") or f.get("team_external_id", "")
    round_number = story.get("round_number")
    made = f["three_points_made"]
    attempted = f["three_points_attempted"]

    headline = f"{name}"
    subtitle = f"Puntería de la jornada · {made} triples"
    caption = (
        f"{name} anota {made} triples ({made}/{attempted}) en la jornada "
        f"{round_number}: el más certero desde el perímetro."
    )
    hashtags = BASE_HASHTAGS + ("Triples",)
    if team:
        hashtags = hashtags + (_slugify(team),)
    return CopyContract(
        headline=headline,
        subtitle=subtitle,
        caption=caption,
        hashtags=hashtags,
        facts_used=("player_name", "team_name", "three_points_made",
                    "three_points_attempted", "round_number"),
    )


def generate_copy_perfect_night(story: Dict[str, Any]) -> CopyContract:
    f = story["facts"]
    name = f.get("player_name") or f.get("player_external_id", "El jugador")
    team = f.get("team_name") or f.get("team_external_id", "")
    round_number = story.get("round_number")
    made = f["field_goals_made"]
    points = f["points"]

    headline = f"{name}"
    subtitle = f"Sin fallar · {made}/{made} en tiros de campo"
    caption = (
        f"Noche perfecta de {name} en la jornada {round_number}: {made} de {made} "
        f"en tiros de campo para {points} puntos, sin un solo fallo."
    )
    hashtags = BASE_HASHTAGS + ("SinFallo",)
    if team:
        hashtags = hashtags + (_slugify(team),)
    return CopyContract(
        headline=headline,
        subtitle=subtitle,
        caption=caption,
        hashtags=hashtags,
        facts_used=("player_name", "team_name", "field_goals_made", "points", "round_number"),
    )


def generate_copy_top_scorer(story: Dict[str, Any]) -> CopyContract:
    f = story["facts"]
    name = f.get("player_name") or f.get("player_external_id", "El jugador")
    team = f.get("team_name") or f.get("team_external_id", "")
    points = f["points"]
    games = f["games_played"]

    headline = f"{name}"
    subtitle = f"Máximo anotador de la temporada · {points} puntos"
    caption = (
        f"{name} es el máximo anotador de la temporada de Segunda FEB con "
        f"{points} puntos en {games} partidos."
    )
    hashtags = BASE_HASHTAGS + ("MaximoAnotador",)
    if team:
        hashtags = hashtags + (_slugify(team),)
    return CopyContract(
        headline=headline,
        subtitle=subtitle,
        caption=caption,
        hashtags=hashtags,
        facts_used=("player_name", "team_name", "points", "games_played"),
    )


def generate_copy_top_rebounder(story: Dict[str, Any]) -> CopyContract:
    f = story["facts"]
    name = f.get("player_name") or f.get("player_external_id", "El jugador")
    team = f.get("team_name") or f.get("team_external_id", "")
    rebounds = f["rebounds"]
    games = f["games_played"]

    headline = f"{name}"
    subtitle = f"Máximo reboteador de la temporada · {rebounds} rebotes"
    caption = (
        f"{name} es el máximo reboteador de la temporada de Segunda FEB con "
        f"{rebounds} rebotes en {games} partidos."
    )
    hashtags = BASE_HASHTAGS + ("Rebotes",)
    if team:
        hashtags = hashtags + (_slugify(team),)
    return CopyContract(
        headline=headline,
        subtitle=subtitle,
        caption=caption,
        hashtags=hashtags,
        facts_used=("player_name", "team_name", "rebounds", "games_played"),
    )


def generate_copy_streak(story: Dict[str, Any]) -> CopyContract:
    f = story["facts"]
    team = f.get("team_name") or f.get("team_external_id", "El equipo")
    length = f["streak_length"]
    is_win = f["streak_kind"] == "win"
    round_number = story.get("round_number")
    word = "victorias" if is_win else "derrotas"

    headline = f"{team}"
    subtitle = f"{length} {word} seguidas"
    caption = (
        f"{team} encadena {length} {word} consecutivas tras la jornada "
        f"{round_number}."
    )
    hashtags = BASE_HASHTAGS + (("Racha",) if is_win else ("MalaRacha",))
    return CopyContract(
        headline=headline,
        subtitle=subtitle,
        caption=caption,
        hashtags=hashtags,
        facts_used=("team_name", "streak_length", "round_number"),
    )


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_GENERATORS = {
    "match_final": generate_copy_match_final,
    "player_of_round": generate_copy_player_of_round,
    "round_recap": generate_copy_round_recap,
    "biggest_win": generate_copy_biggest_win,
    "double_double": generate_copy_notable_performance,
    "triple_double": generate_copy_notable_performance,
    "season_high": generate_copy_season_high,
    "upset": generate_copy_upset,
    "win_streak": generate_copy_streak,
    "loss_streak": generate_copy_streak,
    "stat_leaderboard": generate_copy_stat_leaderboard,
    "iron_man": generate_copy_iron_man,
    "top_assist_provider": generate_copy_playmaker,
    "sharpshooter": generate_copy_sharpshooter,
    "perfect_night": generate_copy_perfect_night,
    "top_scorer": generate_copy_top_scorer,
    "top_rebounder": generate_copy_top_rebounder,
}


def generate_copy(story: Dict[str, Any]) -> CopyContract:
    story_type = story["story_type"]
    generator = _GENERATORS.get(story_type)
    if generator is None:
        raise ValueError(f"No copy generator for story_type {story_type!r}")
    return generator(story)


def _slugify(text: str) -> str:
    cleaned = "".join(c for c in text if c.isalnum())
    return cleaned or "Team"
