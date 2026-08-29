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
    # Subjects only, never the figures: the card carries the numbers.
    subjects: List[str] = []
    hero = f.get("hero") or {}
    top = f.get("top") or {}
    for who in (hero.get("name"), top.get("name")):
        if who and who not in subjects:
            subjects.append(who)
    for tile in f.get("tiles", []):
        sub = (tile.get("sub") or "").split(" ")[0]
        # tile subs start with a team name; keep it clean, drop trailing digits
        if sub and not sub.isdigit() and sub not in subjects:
            subjects.append(sub)
    headline = "La jornada en datos"
    subtitle = f"Jornada {round_number} · lo que hay que saber"
    if len(subjects) >= 2:
        joined = ", ".join(subjects[:-1]) + " y " + subjects[-1]
    else:
        joined = subjects[0] if subjects else ""
    caption = (f"El resumen de la jornada {round_number}: {joined}."
               if joined else f"El resumen de la jornada {round_number}.")
    return CopyContract(
        headline=headline, subtitle=subtitle, caption=caption,
        hashtags=BASE_HASHTAGS + ("Resumen",),
        facts_used=("hero", "top", "tiles", "round_number"),
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


def _count(n: int, singular: str, plural: str) -> str:
    """Spanish counts agree with the noun. A defensive line can legitimately
    read 1 or 0, unlike the assist/three-point cards whose thresholds keep the
    number plural, so this card cannot hardcode the plural."""
    return f"{n} {singular if n == 1 else plural}"


def _years(n: int) -> str:
    return f"{n} año" if n == 1 else f"{n} años"


def generate_copy_young_gun(story: Dict[str, Any]) -> CopyContract:
    f = story["facts"]
    name = f.get("player_name") or f.get("player_external_id", "El jugador")
    team = f.get("team_name") or f.get("team_external_id", "")
    round_number = story.get("round_number")
    age, points = f["age"], f["points"]
    headline = f"{name}"
    subtitle = f"La joven promesa · {_years(age)}"
    caption = (
        f"Con solo {_years(age)}, {name} firmó {points} puntos en la jornada "
        f"{round_number}: el más joven en dar la cara."
    )
    hashtags = BASE_HASHTAGS + ("Cantera",)
    if team:
        hashtags = hashtags + (_slugify(team),)
    return CopyContract(headline=headline, subtitle=subtitle, caption=caption,
                        hashtags=hashtags,
                        facts_used=("player_name", "team_name", "age", "points", "round_number"))


def generate_copy_veteran(story: Dict[str, Any]) -> CopyContract:
    f = story["facts"]
    name = f.get("player_name") or f.get("player_external_id", "El jugador")
    team = f.get("team_name") or f.get("team_external_id", "")
    round_number = story.get("round_number")
    age, points = f["age"], f["points"]
    headline = f"{name}"
    subtitle = f"El veterano · {_years(age)}"
    caption = (
        f"A sus {_years(age)}, {name} sigue mandando: {points} puntos en la "
        f"jornada {round_number}, el más veterano en decidir."
    )
    hashtags = BASE_HASHTAGS + ("Veterania",)
    if team:
        hashtags = hashtags + (_slugify(team),)
    return CopyContract(headline=headline, subtitle=subtitle, caption=caption,
                        hashtags=hashtags,
                        facts_used=("player_name", "team_name", "age", "points", "round_number"))


def generate_copy_lone_flag(story: Dict[str, Any]) -> CopyContract:
    """The country is the story, so it leads. Phrased as "de la liga" on
    purpose: the FEB records ONE nationality per player, so this is a claim
    about the federation's roster, not about anybody's passports."""
    f = story["facts"]
    name = f.get("player_name") or f.get("player_external_id", "El jugador")
    team = f.get("team_name") or f.get("team_external_id", "")
    round_number = story.get("round_number")
    country = f["nationality"]
    points = f["points"]
    rebounds = f["rebounds"]

    headline = f"{name}"
    subtitle = f"El único de {country} · {points} puntos"
    caption = (
        f"{name} es el único jugador de {country} en toda la Segunda FEB esta "
        f"temporada. En la jornada {round_number} firmó {points} puntos y "
        f"{rebounds} rebotes."
    )
    hashtags = BASE_HASHTAGS + ("Internacional",)
    if team:
        hashtags = hashtags + (_slugify(team),)
    return CopyContract(
        headline=headline,
        subtitle=subtitle,
        caption=caption,
        hashtags=hashtags,
        facts_used=(
            "player_name", "team_name", "nationality", "points", "rebounds",
            "round_number",
        ),
    )


def generate_copy_best_five(story: Dict[str, Any]) -> CopyContract:
    f = story["facts"]
    round_number = story.get("round_number")
    lineup = f.get("lineup", [])
    ideal = story.get("story_type") == "best_five_ideal"
    names = [r.get("player_name") or r.get("player_external_id", "") for r in lineup]
    # Names only, no figures: the numbers live on the card and are checked there;
    # keeping them out of the caption keeps the prose from mis-stating a note.
    if len(names) >= 2:
        joined = ", ".join(names[:-1]) + " y " + names[-1]
    else:
        joined = names[0] if names else ""
    if ideal:
        headline = "El quinteto ideal"
        subtitle = f"La mejor alineación por posición · jornada {round_number}"
        caption = (
            f"El quinteto ideal de la jornada {round_number}, uno por posición: "
            f"{joined}."
        )
    else:
        headline = "El quinteto de la jornada"
        subtitle = f"Los 5 mejores por nota · jornada {round_number}"
        caption = (
            f"El mejor quinteto de la jornada {round_number} por nota FEB: {joined}."
        )
    return CopyContract(
        headline=headline, subtitle=subtitle, caption=caption,
        hashtags=BASE_HASHTAGS + ("QuintetoIdeal",),
        facts_used=("lineup", "round_number"),
    )


def generate_copy_defensive_anchor(story: Dict[str, Any]) -> CopyContract:
    f = story["facts"]
    name = f.get("player_name") or f.get("player_external_id", "El jugador")
    team = f.get("team_name") or f.get("team_external_id", "")
    round_number = story.get("round_number")
    steals = f["steals"]
    blocks = f["blocks"]
    actions = f["defensive_actions"]
    points = f["points"]

    headline = f"{name}"
    subtitle = f"El muro · {_count(steals, 'robo', 'robos')} y {_count(blocks, 'tapón', 'tapones')}"
    # Deliberately does NOT lead with points: the whole reason this card exists
    # is that the defensive line is the story, whatever the scoring says.
    caption = (
        f"{name} se hace dueño de la jornada {round_number} sin necesidad de "
        f"anotar: {_count(steals, 'robo', 'robos')} y "
        f"{_count(blocks, 'tapón', 'tapones')}, {actions} acciones defensivas, "
        f"las que más. Cerró con {_count(points, 'punto', 'puntos')}."
    )
    hashtags = BASE_HASHTAGS + ("Defensa",)
    if team:
        hashtags = hashtags + (_slugify(team),)
    return CopyContract(
        headline=headline,
        subtitle=subtitle,
        caption=caption,
        hashtags=hashtags,
        facts_used=(
            "player_name", "team_name", "steals", "blocks",
            "defensive_actions", "points", "round_number",
        ),
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


def generate_copy_season_assist_leader(story: Dict[str, Any]) -> CopyContract:
    f = story["facts"]
    name = f.get("player_name") or f.get("player_external_id", "El jugador")
    team = f.get("team_name") or f.get("team_external_id", "")
    assists = f["assists"]
    games = f["games_played"]

    headline = f"{name}"
    subtitle = f"Máximo asistente de la temporada · {assists} asistencias"
    caption = (
        f"{name} es el máximo asistente de la temporada de Segunda FEB con "
        f"{assists} asistencias en {games} partidos."
    )
    hashtags = BASE_HASHTAGS + ("Asistencias",)
    if team:
        hashtags = hashtags + (_slugify(team),)
    return CopyContract(
        headline=headline,
        subtitle=subtitle,
        caption=caption,
        hashtags=hashtags,
        facts_used=("player_name", "team_name", "assists", "games_played"),
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


def generate_copy_best_duo(story: Dict[str, Any]) -> CopyContract:
    f = story["facts"]
    n1 = f.get("p1_name") or f.get("p1_external_id", "Jugador 1")
    n2 = f.get("p2_name") or f.get("p2_external_id", "Jugador 2")
    team = f.get("team_name") or f.get("team_external_id", "")
    round_number = story.get("round_number")
    p1 = f["p1_points"]
    p2 = f["p2_points"]
    combined = f["combined_points"]

    headline = f"{n1} & {n2}"
    subtitle = f"El mejor dúo de la jornada {round_number}"
    caption = (
        f"{n1} ({p1}) y {n2} ({p2}) suman {combined} puntos: el mejor dúo de la "
        f"jornada {round_number} de Segunda FEB."
    )
    hashtags = BASE_HASHTAGS + ("MejorDuo",)
    if team:
        hashtags = hashtags + (_slugify(team),)
    return CopyContract(
        headline=headline,
        subtitle=subtitle,
        caption=caption,
        hashtags=hashtags,
        facts_used=("p1_name", "p2_name", "p1_points", "p2_points",
                    "combined_points", "round_number"),
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
    "playmaker": generate_copy_playmaker,                        # round director
    "best_five": generate_copy_best_five,                        # quinteto de la jornada
    "best_five_ideal": generate_copy_best_five,                  # quinteto ideal por posición
    "defensive_anchor": generate_copy_defensive_anchor,          # steals + blocks
    "lone_flag": generate_copy_lone_flag,                        # bio: nationality
    "young_gun": generate_copy_young_gun,                        # bio: youngest
    "veteran": generate_copy_veteran,                            # bio: oldest
    "sharpshooter": generate_copy_sharpshooter,
    "perfect_night": generate_copy_perfect_night,
    "top_scorer": generate_copy_top_scorer,                      # season leaders
    "top_rebounder": generate_copy_top_rebounder,
    "top_assist_provider": generate_copy_season_assist_leader,
    "best_duo": generate_copy_best_duo,
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
