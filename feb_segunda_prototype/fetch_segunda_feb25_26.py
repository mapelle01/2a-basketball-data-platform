#!/usr/bin/env python3
import argparse
import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup


BASE_URL = 'https://baloncestoenvivo.feb.es'
COMP_ID = 2
COMP_CODE = 'segundafeb'
SEASON = '2025'
RESULTS_URL = f'{BASE_URL}/resultados.aspx?g={COMP_ID}&t={SEASON}&nm={COMP_CODE}'
RANKINGS_URL = f'{BASE_URL}/rankings.aspx?g={COMP_ID}&t={SEASON}&nm={COMP_CODE}'
RAW_DIR = Path('data') / 'raw' / f'{COMP_CODE}_{SEASON}'
DB_PATH = Path('feb_segunda_2025.db')
HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; FEBScraper/1.0; +https://example.com)'}


def safe_int(value):
    if value is None:
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return None


def safe_float(value):
    if value is None:
        return None
    if isinstance(value, float):
        return value
    try:
        return float(str(value).strip().replace(',', '.'))
    except (ValueError, TypeError):
        return None


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def fetch_url(session: requests.Session, url: str):
    resp = session.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def parse_results_page(html: str):
    soup = BeautifulSoup(html, 'lxml')
    rows = soup.select('table#_ctl0_MainContentPlaceHolderMaster_jornadaDataGrid tr')
    matches = []
    for row in rows[1:]:
        cells = row.find_all(['td', 'th'])
        if len(cells) < 4:
            continue
        team_text = ' '.join(cells[0].stripped_strings)
        score_text = cells[1].text.strip()
        date_text = cells[2].text.strip()
        time_text = cells[3].text.strip()
        link = cells[1].find('a')
        if not link or 'href' not in link.attrs:
            continue
        match_url = link['href']
        match_id_match = re.search(r'[?&]p=(\d+)', match_url)
        if not match_id_match:
            continue
        match_id = int(match_id_match.group(1))

        home_name, away_name = parse_team_names(team_text)
        home_score, away_score = parse_score(score_text)
        start_time = parse_datetime(date_text, time_text)

        matches.append({
            'match_id': match_id,
            'match_url': match_url,
            'home_team_name': home_name,
            'away_team_name': away_name,
            'score_text': score_text,
            'home_score': home_score,
            'away_score': away_score,
            'start_time': start_time,
            'date_text': date_text,
            'time_text': time_text,
        })
    return matches


def parse_team_names(team_text: str):
    parts = re.split(r'\s*-\s*', team_text, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return team_text.strip(), ''


def parse_score(score_text: str):
    if not score_text or score_text.strip() in ('*-*', '--', 'x-x'):
        return None, None
    parts = score_text.split('-')
    if len(parts) != 2:
        return None, None
    return safe_int(parts[0].strip()), safe_int(parts[1].strip())


def parse_datetime(date_text: str, time_text: str):
    if not date_text:
        return None
    if not time_text:
        time_text = '00:00'
    try:
        return datetime.strptime(f'{date_text} {time_text}', '%d/%m/%Y %H:%M').isoformat(sep=' ')
    except ValueError:
        return None


def parse_classification(html: str):
    soup = BeautifulSoup(html, 'lxml')
    rows = soup.select('table#_ctl0_MainContentPlaceHolderMaster_clasificacionFinalDataGrid tr')
    standings = []
    for row in rows[1:]:
        cells = [x.text.strip() for x in row.find_all(['td', 'th'])]
        if len(cells) < 2:
            continue
        standings.append({'position': safe_int(cells[0]), 'team_name': cells[1]})
    return standings


def parse_ranking_leaders(html: str):
    soup = BeautifulSoup(html, 'lxml')
    header = soup.find('h1')
    title = header.text.strip() if header else 'Rankings'
    rows = soup.select('table#_ctl0_MainContentPlaceHolderMaster_rankingAcumuladosDataGrid tr')
    leaders = []
    for row in rows[1:]:
        cells = [x.text.strip() for x in row.find_all(['td', 'th'])]
        if len(cells) < 5:
            continue
        leaders.append({
            'category': title,
            'player_name': cells[0],
            'team_name': cells[1],
            'total': safe_float(cells[2]),
            'games': safe_int(cells[3]),
            'average': safe_float(cells[4]),
        })
    return leaders


def extract_token_from_match_page(html: str):
    soup = BeautifulSoup(html, 'lxml')
    field = soup.select_one('#contentToken input')
    if field and field.has_attr('value'):
        return field['value']
    return None


def fetch_live_stats(session: requests.Session, token: str, endpoint: str, match_id: int, referer: str):
    api_url = f'https://intrafeb.feb.es/LiveStats.API/api/v1/{endpoint}/{match_id}'
    headers = {
        'Authorization': f'Bearer {token}',
        'User-Agent': HEADERS['User-Agent'],
        'Accept': 'application/json',
        'Referer': referer,
    }
    resp = session.get(api_url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def save_json(obj, path: Path):
    with path.open('w', encoding='utf-8') as handle:
        json.dump(obj, handle, indent=2, ensure_ascii=False)


def init_db(db_path: Path):
    conn = sqlite3.connect(str(db_path))
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS competitions (
            competition_code TEXT PRIMARY KEY,
            competition_name TEXT
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS seasons (
            season_code TEXT PRIMARY KEY,
            competition_code TEXT,
            FOREIGN KEY (competition_code) REFERENCES competitions(competition_code)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS teams (
            team_id TEXT PRIMARY KEY,
            name TEXT,
            logo_url TEXT
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS players (
            player_id TEXT PRIMARY KEY,
            name TEXT,
            number TEXT,
            team_id TEXT,
            logo_url TEXT,
            FOREIGN KEY (team_id) REFERENCES teams(team_id)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS matches (
            match_id INTEGER PRIMARY KEY,
            competition_code TEXT,
            season_code TEXT,
            match_url TEXT,
            home_team_name TEXT,
            away_team_name TEXT,
            home_score INTEGER,
            away_score INTEGER,
            score_text TEXT,
            start_time TEXT,
            round_name TEXT,
            status TEXT,
            status_text TEXT,
            place TEXT,
            field TEXT,
            referee1 TEXT,
            referee2 TEXT,
            referee3 TEXT,
            fetched_at TEXT,
            raw_boxscore_path TEXT,
            raw_teamstats_path TEXT,
            raw_keyfacts_path TEXT,
            raw_shotchart_path TEXT,
            raw_ranking_path TEXT
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS player_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER,
            player_id TEXT,
            team_id TEXT,
            name TEXT,
            number TEXT,
            minutes TEXT,
            points INTEGER,
            rebounds INTEGER,
            assists INTEGER,
            steals INTEGER,
            blocks INTEGER,
            turnovers INTEGER,
            fouls INTEGER,
            value INTEGER,
            field_goals_made INTEGER,
            field_goals_attempted INTEGER,
            triple_made INTEGER,
            triple_attempted INTEGER,
            free_throw_made INTEGER,
            free_throw_attempted INTEGER,
            raw_json TEXT,
            FOREIGN KEY (match_id) REFERENCES matches(match_id),
            FOREIGN KEY (player_id) REFERENCES players(player_id),
            FOREIGN KEY (team_id) REFERENCES teams(team_id)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS team_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER,
            team_id TEXT,
            name TEXT,
            points INTEGER,
            fouls INTEGER,
            rebounds INTEGER,
            assists INTEGER,
            turnovers INTEGER,
            field_goals_made INTEGER,
            field_goals_attempted INTEGER,
            three_pointers_made INTEGER,
            three_pointers_attempted INTEGER,
            free_throws_made INTEGER,
            free_throws_attempted INTEGER,
            raw_json TEXT,
            FOREIGN KEY (match_id) REFERENCES matches(match_id),
            FOREIGN KEY (team_id) REFERENCES teams(team_id)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS standings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            season_code TEXT,
            position INTEGER,
            team_name TEXT,
            inserted_at TEXT
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS leaderboards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            season_code TEXT,
            category TEXT,
            rank INTEGER,
            player_name TEXT,
            team_name TEXT,
            total REAL,
            games INTEGER,
            average REAL,
            inserted_at TEXT
        )
    ''')
    return conn


def upsert_competition(conn):
    conn.execute('INSERT OR IGNORE INTO competitions (competition_code, competition_name) VALUES (?, ?)',
                 (COMP_CODE, 'SEGUNDA FEB'))
    conn.execute('INSERT OR IGNORE INTO seasons (season_code, competition_code) VALUES (?, ?)',
                 (SEASON, COMP_CODE))


def upsert_team(conn, team_id: str, name: str, logo_url: str = None):
    if team_id is None:
        return
    conn.execute('INSERT OR IGNORE INTO teams (team_id, name, logo_url) VALUES (?, ?, ?)',
                 (team_id, name, logo_url))


def upsert_player(conn, player_id: str, name: str, number: str, team_id: str, logo_url: str = None):
    if player_id is None:
        return
    conn.execute('INSERT OR IGNORE INTO players (player_id, name, number, team_id, logo_url) VALUES (?, ?, ?, ?, ?)',
                 (player_id, name, number, team_id, logo_url))


def insert_match(conn, match):
    conn.execute('''
        INSERT OR REPLACE INTO matches (
            match_id, competition_code, season_code, match_url,
            home_team_name, away_team_name, home_score, away_score, score_text,
            start_time, round_name, status, status_text, place, field,
            referee1, referee2, referee3, fetched_at,
            raw_boxscore_path, raw_teamstats_path, raw_keyfacts_path, raw_shotchart_path, raw_ranking_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        match['match_id'], COMP_CODE, SEASON, match['match_url'],
        match['home_team_name'], match['away_team_name'], match['home_score'], match['away_score'], match['score_text'],
        match.get('start_time'), match.get('round_name'), match.get('status'), match.get('status_text'),
        match.get('place'), match.get('field'), match.get('referee1'), match.get('referee2'), match.get('referee3'),
        datetime.utcnow().isoformat(sep=' '),
        match.get('raw_boxscore_path'), match.get('raw_teamstats_path'), match.get('raw_keyfacts_path'),
        match.get('raw_shotchart_path'), match.get('raw_ranking_path')
    ))


def insert_player_stats(conn, match_id: int, team_id: str, team_name: str, player):
    player_id = player.get('id')
    name = player.get('name')
    number = player.get('no')
    upsert_player(conn, player_id, name, number, team_id, player.get('logo'))
    conn.execute('''
        INSERT INTO player_stats (
            match_id, player_id, team_id, name, number,
            minutes, points, rebounds, assists, steals, blocks,
            turnovers, fouls, value, field_goals_made, field_goals_attempted,
            triple_made, triple_attempted, free_throw_made, free_throw_attempted, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        match_id, player_id, team_id, name, number,
        player.get('minFormatted'), safe_int(player.get('pts')), safe_int(player.get('reb')),
        safe_int(player.get('assist')), safe_int(player.get('st')), safe_int(player.get('bs')),
        safe_int(player.get('to')), safe_int(player.get('pf')), safe_int(player.get('val')),
        safe_int(player.get('fgm')), safe_int(player.get('fga')),
        safe_int(player.get('p3m')), safe_int(player.get('p3a')),
        safe_int(player.get('p1m')), safe_int(player.get('p1a')), json.dumps(player, ensure_ascii=False)
    ))


def insert_team_stats(conn, match_id: int, team):
    team_id = team.get('id')
    name = team.get('name')
    upsert_team(conn, team_id, name, team.get('logo'))
    conn.execute('''
        INSERT INTO team_stats (
            match_id, team_id, name, points, fouls, rebounds,
            assists, turnovers, field_goals_made, field_goals_attempted,
            three_pointers_made, three_pointers_attempted, free_throws_made,
            free_throws_attempted, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        match_id, team_id, name,
        safe_int(team.get('pts')), safe_int(team.get('fouls')),
        safe_int(team.get('rd')) + safe_int(team.get('ro')) if team.get('rd') or team.get('ro') else None,
        safe_int(team.get('assist')), safe_int(team.get('to')),
        safe_int(team.get('fgm')), safe_int(team.get('fga')),
        safe_int(team.get('p3m')), safe_int(team.get('p3a')),
        safe_int(team.get('p1m')), safe_int(team.get('p1a')),
        json.dumps(team, ensure_ascii=False)
    ))


def insert_standings(conn, standings):
    conn.execute('DELETE FROM standings WHERE season_code = ?', (SEASON,))
    for standing in standings:
        conn.execute('INSERT INTO standings (season_code, position, team_name, inserted_at) VALUES (?, ?, ?, ?)',
                     (SEASON, standing['position'], standing['team_name'], datetime.utcnow().isoformat(sep=' ')))


def insert_leaders(conn, leaders):
    conn.execute('DELETE FROM leaderboards WHERE season_code = ?', (SEASON,))
    for rank, leader in enumerate(leaders, start=1):
        conn.execute('INSERT INTO leaderboards (season_code, category, rank, player_name, team_name, total, games, average, inserted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                     (SEASON, leader['category'], rank, leader['player_name'], leader['team_name'], leader['total'], leader['games'], leader['average'], datetime.utcnow().isoformat(sep=' ')))


def normalize_and_store_match(conn, match, raw_dir: Path, responses: dict):
    mix = dict(match)
    for key, data in responses.items():
        if data is None:
            continue
        filename = raw_dir / f'{match["match_id"]}_{key}.json'
        save_json(data, filename)
        mix[f'raw_{key.lower()}_path'] = str(filename)

    boxscore = responses.get('BoxScore')
    if boxscore and isinstance(boxscore, dict):
        header = boxscore.get('HEADER') or boxscore.get('BOXSCORE', {}).get('HEADER', {})
        mix.update({
            'round_name': header.get('roundName') or header.get('round') or header.get('competitionRound'),
            'status': header.get('matchStatus') or header.get('status'),
            'status_text': header.get('statusText') or header.get('matchStatusText'),
            'place': header.get('arena') or header.get('place'),
            'field': header.get('court') or header.get('field'),
            'referee1': header.get('ref1') or header.get('referee1'),
            'referee2': header.get('ref2') or header.get('referee2'),
            'referee3': header.get('ref3') or header.get('referee3'),
        })

    insert_match(conn, mix)

    teamstats = responses.get('TeamStats')
    if boxscore and isinstance(boxscore, dict):
        boxscore_teams = boxscore.get('BOXSCORE', {}).get('TEAM', [])
        for team in boxscore_teams:
            insert_team_stats(conn, match['match_id'], team)
            for player in team.get('PLAYER', []):
                insert_player_stats(conn, match['match_id'], team.get('id'), team.get('name'), player)
    elif teamstats and isinstance(teamstats, dict):
        for team in teamstats.get('TEAMSTATS', {}).get('TEAM', []):
            insert_team_stats(conn, match['match_id'], team)


def main(limit: int):
    ensure_dir(RAW_DIR)
    session = requests.Session()
    print('Fetching results page from', RESULTS_URL)
    results_html = fetch_url(session, RESULTS_URL)
    matches = parse_results_page(results_html)
    if not matches:
        raise RuntimeError('No matches parsed from results page')
    print(f'Parsed {len(matches)} match rows, limiting to {limit}')
    matches = matches[:limit]

    conn = init_db(DB_PATH)
    upsert_competition(conn)

    print('Fetching classification for season')
    classification_html = fetch_url(session, RESULTS_URL)
    standings = parse_classification(classification_html)
    insert_standings(conn, standings)
    print(f'Inserted {len(standings)} standings rows')

    print('Fetching ranking leaders page')
    ranking_html = fetch_url(session, RANKINGS_URL)
    leaders = parse_ranking_leaders(ranking_html)
    insert_leaders(conn, leaders)
    print(f'Inserted {len(leaders)} leaderboard rows')

    for match in matches:
        print('Processing match', match['match_id'], match['home_team_name'], 'vs', match['away_team_name'])
        match_html = fetch_url(session, match['match_url'])
        token = extract_token_from_match_page(match_html)
        if not token:
            print('  WARNING: no token extracted for match', match['match_id'])
            continue
        raw_match_path = RAW_DIR / f'{match["match_id"]}_page.html'
        raw_match_path.write_text(match_html, encoding='utf-8')
        match['raw_match_page_path'] = str(raw_match_path)

        responses = {}
        for endpoint in ['BoxScore', 'TeamStats', 'KeyFacts', 'ShotChart', 'Ranking']:
            try:
                data = fetch_live_stats(session, token, endpoint, match['match_id'], match['match_url'])
                responses[endpoint] = data
                print('  fetched', endpoint, 'size', len(json.dumps(data)))
            except Exception as exc:
                print('  ERROR fetching', endpoint, exc)
                responses[endpoint] = None

        normalize_and_store_match(conn, match, RAW_DIR, responses)
        conn.commit()

    conn.commit()
    conn.close()
    print('Prototype run complete. DB stored at', DB_PATH)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='FEB Segunda FEB 2025/2026 prototype extractor')
    parser.add_argument('--limit', type=int, default=5, help='Maximum number of matches to fetch')
    parser.add_argument('--db', type=Path, default=DB_PATH, help='SQLite database path')
    parser.add_argument('--data-dir', type=Path, default=Path('data'), help='Base data directory')
    args = parser.parse_args()
    DB_PATH = args.db
    RAW_DIR = args.data_dir / 'raw' / f'{COMP_CODE}_{SEASON}'
    main(args.limit)
