"""
Computes series win probabilities by game state for NBA best-of-7 playoff series.
Covers all best-of-7 series (detected by winner reaching exactly 4 wins) from
1947 onward. Pre-1997 data comes from basketball-reference; 1997+ from nba_api.

Usage: python src/series_win_probability.py
"""

import os
import sys
import pickle
from collections import defaultdict

import pandas as pd

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SRC_DIR)
sys.path.insert(0, _SRC_DIR)

from fetch_playoffs import build_playoff_games, _format_season
from scrape_bbref import build_playoff_games_bbref

# Stores {year: games_df} so the filter can be changed without re-fetching.
_SEASONS_CACHE = os.path.join(_PROJECT_ROOT, "data", "playoff_seasons_cache.pkl")
START_YEAR = 1947  # BBref covers BAA/NBA from 1946-47 onward
END_YEAR = 2025


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def _load_seasons_cache(start, end):
    """
    Returns {year: games_df} for all seasons, fetching from nba_api only when needed.
    Cached per-season so filter changes never require re-fetching.
    """
    os.makedirs(os.path.dirname(_SEASONS_CACHE), exist_ok=True)

    if os.path.exists(_SEASONS_CACHE):
        with open(_SEASONS_CACHE, "rb") as f:
            cache = pickle.load(f)
        # Only fetch seasons that aren't in the cache yet
        missing = [y for y in range(start, end + 1) if y not in cache]
    else:
        cache = {}
        missing = list(range(start, end + 1))

    if missing:
        bbref_years = [y for y in missing if y < 1997]
        api_years   = [y for y in missing if y >= 1997]
        if bbref_years:
            print(f"Fetching {len(bbref_years)} season(s) from basketball-reference (~3.5 s each)...")
        if api_years:
            print(f"Fetching {len(api_years)} season(s) from nba_api...")
        for year in missing:
            label = _format_season(year)
            print(f"  {label} ...", end=" ", flush=True)
            try:
                if year < 1997:
                    cache[year] = build_playoff_games_bbref(year)
                else:
                    cache[year] = build_playoff_games(year)
                print("ok")
            except Exception as exc:
                print(f"SKIP ({exc})")
                cache[year] = pd.DataFrame()  # cache the miss so we never retry it
        with open(_SEASONS_CACHE, "wb") as f:
            pickle.dump(cache, f)

    return {y: cache[y] for y in range(start, end + 1) if y in cache}


def load_or_fetch_all_series(start=START_YEAR, end=END_YEAR):
    """
    Builds a list of all valid best-of-7 playoff series (4–7 games).
    Loads raw season data from cache; filtering happens here so the cache
    never needs to be invalidated when the series-length filter changes.
    """
    seasons = _load_seasons_cache(start, end)

    all_series = []
    for year in sorted(seasons):
        games_df = seasons[year]
        if games_df.empty:
            continue  # year failed to fetch; cached as empty sentinel
        count = 0
        for series_id, grp in games_df.groupby("series_id"):
            # Best-of-7: series ends when one team reaches 4 wins (4–7 games).
            if not (4 <= len(grp) <= 7):
                continue
            grp_sorted = grp.sort_values("game_num").reset_index(drop=True)

            # Validate: all games must involve exactly the same two teams.
            # Old nba_api series_ids sometimes bundle unrelated matchups together.
            all_teams = set(grp_sorted["home_team"]) | set(grp_sorted["away_team"])
            if len(all_teams) != 2:
                continue

            win_counts = grp_sorted["winner"].value_counts()
            # Best-of-7 series: the winner always reaches exactly 4 wins.
            # This cleanly excludes best-of-5 (3 wins) and best-of-3 (2 wins) series
            # present in pre-1984 seasons without needing per-year format knowledge.
            if win_counts.iloc[0] != 4:
                continue

            series_winner = win_counts.index[0]
            team_a = grp_sorted.iloc[0]["home_team"]

            all_series.append({
                "series_id": series_id,
                "season": year,
                "num_games": len(grp_sorted),
                "team_a": team_a,
                "team_b": grp_sorted.iloc[0]["away_team"],
                "series_winner": series_winner,
                "team_a_won": series_winner == team_a,
                "games": grp_sorted,
            })
            count += 1

    print(f"Loaded {len(all_series)} best-of-7 series ({start}-{end})")
    return all_series


# ---------------------------------------------------------------------------
# State probability computation
# ---------------------------------------------------------------------------

_TEAM_ABBR = {
    # Modern franchises
    "Atlanta Hawks": "ATL",
    "Boston Celtics": "BOS",
    "Brooklyn Nets": "BKN",
    "Charlotte Bobcats": "CHA",
    "Charlotte Hornets": "CHH",
    "Chicago Bulls": "CHI",
    "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL",
    "Denver Nuggets": "DEN",
    "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW",
    "Houston Rockets": "HOU",
    "Indiana Pacers": "IND",
    "Los Angeles Clippers": "LAC",
    "Los Angeles Lakers": "LAL",
    "Memphis Grizzlies": "MEM",
    "Miami Heat": "MIA",
    "Milwaukee Bucks": "MIL",
    "Minnesota Timberwolves": "MIN",
    "New Jersey Nets": "NJN",
    "New Orleans Hornets": "NOH",
    "New Orleans Pelicans": "NOP",
    "New Orleans/Oklahoma City Hornets": "NOK",
    "New York Knicks": "NYK",
    "New York Knickerbockers": "NYK",
    "Oklahoma City Thunder": "OKC",
    "Orlando Magic": "ORL",
    "Philadelphia 76ers": "PHI",
    "Phoenix Suns": "PHX",
    "Portland Trail Blazers": "POR",
    "Sacramento Kings": "SAC",
    "San Antonio Spurs": "SAS",
    "Seattle SuperSonics": "SEA",
    "Toronto Raptors": "TOR",
    "Utah Jazz": "UTA",
    "Vancouver Grizzlies": "VAN",
    "Washington Bullets": "WSB",
    "Washington Capitols": "WSC",
    "Washington Wizards": "WAS",
    # Relocated / historical franchises
    "Anderson Packers": "AND",
    "Baltimore Bullets": "BAL",
    "Buffalo Braves": "BUF",
    "Capital Bullets": "CAP",
    "Chicago Packers": "CHP",
    "Chicago Stags": "STG",
    "Chicago Zephyrs": "CHZ",
    "Cincinnati Royals": "CIN",
    "Cleveland Rebels": "CRB",
    "Denver Rockets": "DNR",
    "Detroit Falcons": "DTF",
    "Fort Wayne Pistons": "FTW",
    "Indianapolis Jets": "INJ",
    "Indianapolis Olympians": "INO",
    "Kansas City Kings": "KCK",
    "Kansas City-Omaha Kings": "KCO",
    "Memphis Pros": "MEM",
    "Milwaukee Hawks": "MLW",
    "Minneapolis Lakers": "MNL",
    "New Orleans Jazz": "NOJ",
    "New York Nets": "NYN",
    "Philadelphia Warriors": "PHW",
    "Pittsburgh Ironmen": "PIT",
    "Providence Steamrollers": "PRO",
    "Rochester Royals": "ROC",
    "San Diego Clippers": "SDC",
    "San Diego Rockets": "SDR",
    "San Francisco Warriors": "SFW",
    "Sheboygan Redskins": "SHE",
    "St. Louis Bombers": "STB",
    "St. Louis Hawks": "STL",
    "Syracuse Nationals": "SYR",
    "Toronto Huskies": "TRH",
    "Tri-Cities Blackhawks": "TCB",
    "Waterloo Hawks": "WAT",
}


def _abbr(name: str) -> str:
    """Return the 3-letter team abbreviation, or the original string if already short / unknown."""
    return _TEAM_ABBR.get(name, name)


def _round_abbr(series_id):
    """
    Returns round abbreviation from a series_id string.
    BBref synthetic IDs: B{year}{round_digit}{idx} — round at position 5.
    nba_api IDs: round at position 7 (from 2002 onward; position 7 == '0' pre-2002).
    """
    s = str(series_id)
    if s.startswith('B'):
        # BBref format: B + 4-digit year + round_digit + 2-digit index
        if len(s) >= 7:
            return {'1': '(1)', '2': '(2)', '3': '(CF)', '4': '(F)'}.get(s[5], '')
        return ''
    if len(s) < 8 or s[7] == '0':
        return ''
    return {'1': '(1)', '2': '(2)', '3': '(CF)', '4': '(F)'}.get(s[7], '')


def build_state_records(all_series):
    """
    Returns six dicts, all tracking outcomes from the higher seed's perspective.

    records_hi/lo/tied: {state: [higher_seed_won, total]}
      hi   — higher seed (team_a) leads; state key = (hi_wins, lo_wins)
      lo   — lower seed  (team_b) leads; state key = (lo_wins, hi_wins)
      tied — equal wins;                 state key = (wins, wins)

    recency_hi/lo/tied: {state: {'higher': last_entry, 'lower': last_entry}}
      last_entry = (season, winner_team, loser_team, round_abbr)

    team_a is the home team in game 1, treated as the higher seed.
    """
    records_hi   = defaultdict(lambda: [0, 0])
    records_lo   = defaultdict(lambda: [0, 0])
    records_tied = defaultdict(lambda: [0, 0])
    recency_hi   = {}
    recency_lo   = {}
    recency_tied = {}

    for series in sorted(all_series, key=lambda s: s["season"]):
        games        = series["games"]
        team_a       = series["team_a"]
        team_b       = series["team_b"]
        team_a_won   = series["team_a_won"]
        season       = series["season"]
        series_id    = series["series_id"]
        winner_team  = series["series_winner"]
        loser_team   = team_b if team_a_won else team_a
        rnd          = _round_abbr(series_id)

        ta_wins = 0
        tb_wins = 0

        for _, game in games.iterrows():
            a, b = ta_wins, tb_wins

            if a > b:
                state   = (a, b)
                recs    = records_hi
                rec_map = recency_hi
            elif b > a:
                state   = (b, a)
                recs    = records_lo
                rec_map = recency_lo
            else:
                state   = (a, b)
                recs    = records_tied
                rec_map = recency_tied

            recs[state][1] += 1
            if team_a_won:
                recs[state][0] += 1

            rec = rec_map.setdefault(state, {"higher": None, "lower": None})
            entry = (season, winner_team, loser_team, rnd)
            if team_a_won:
                rec["higher"] = entry
            else:
                rec["lower"] = entry

            if game["winner"] == team_a:
                ta_wins += 1
            else:
                tb_wins += 1

    return records_hi, records_lo, records_tied, recency_hi, recency_lo, recency_tied


def _pct_from(state, records):
    """Higher seed win% from the given records dict."""
    won, total = records.get(state, [0, 0])
    return (won / total * 100) if total > 0 else None


# ---------------------------------------------------------------------------
# Table formatting
# ---------------------------------------------------------------------------

ALL_STATES = [
    (0, 0),
    (1, 0),
    (1, 1),
    (2, 0),
    (2, 1),
    (2, 2),
    (3, 0),
    (3, 1),
    (3, 2),
    (3, 3),
]

# Two rows per non-tied state: higher seed leading, then lower seed leading.
# (kind, a, b):
#   'tied' → tied a-a            (records_tied key: (a, a))
#   'hi'   → higher seed leads   (records_hi   key: (a, b), score hi-lo)
#   'lo'   → lower seed leads    (records_lo   key: (a, b) where a=lo_wins, b=hi_wins)
EXPANDED_STATES = [
    ('tied', 0, 0),
    ('hi',   1, 0),
    ('lo',   1, 0),
    ('tied', 1, 1),
    ('hi',   2, 0),
    ('lo',   2, 0),
    ('hi',   2, 1),
    ('lo',   2, 1),
    ('tied', 2, 2),
    ('hi',   3, 0),
    ('lo',   3, 0),
    ('hi',   3, 1),
    ('lo',   3, 1),
    ('hi',   3, 2),
    ('lo',   3, 2),
    ('tied', 3, 3),
]


def _state_label(kind, a, b):
    if kind == 'tied':
        return "0-0 (Start)" if a == 0 else f"Tied  {a}-{a}"
    if kind == 'hi':
        return f"Higher seed leads {a}-{b}"
    # 'lo': lower seed has 'a' wins, higher seed has 'b'; score from hi perspective is b-a
    return f"Lower seed leads {b}-{a}"


def _fmt(v, *, sign=False):
    if v is None:
        return "N/A"
    if sign:
        return f"+{v:.1f}%" if v >= 0 else f"{v:.1f}%"
    return f"{v:.1f}%"


def _swing_str(new_pct, cur_pct):
    """Format change in higher seed win% between two states."""
    if new_pct is None or cur_pct is None:
        return "N/A"
    diff = new_pct - cur_pct
    return f"+{diff:.1f}%" if diff >= 0 else f"{diff:.1f}%"


def _recent(entry):
    """Format a recency entry (season, winner, loser, round) as a short string."""
    if entry is None:
        return "N/A"
    season, winner, loser, *rest = entry
    rnd = rest[0] if rest else ''
    suffix = f" {rnd}" if rnd else ''
    return f"{season} {_abbr(winner)} over {_abbr(loser)}{suffix}"


def build_output_table(records_hi, records_lo, records_tied,
                       recency_hi, recency_lo, recency_tied):
    rows = []
    for (kind, a, b) in EXPANDED_STATES:
        if kind == 'tied':
            recs, rec_map, state = records_tied, recency_tied, (a, b)
        elif kind == 'hi':
            recs, rec_map, state = records_hi, recency_hi, (a, b)
        else:
            recs, rec_map, state = records_lo, recency_lo, (a, b)

        won, total = recs.get(state, [0, 0])
        hi_pct = (won / total * 100) if total > 0 else None
        lo_pct = (100.0 - hi_pct) if hi_pct is not None else None

        # Higher seed win% after higher seed wins next game
        if kind == 'hi':
            new_hi_if_hi = 100.0 if a + 1 == 4 else _pct_from((a + 1, b), records_hi)
        elif kind == 'lo':
            b1 = b + 1
            new_hi_if_hi = (
                _pct_from((a, a), records_tied) if b1 == a
                else _pct_from((a, b1), records_lo)
            )
        else:  # tied
            new_hi_if_hi = 100.0 if a + 1 == 4 else _pct_from((a + 1, a), records_hi)

        # Higher seed win% after lower seed wins next game
        if kind == 'hi':
            b1 = b + 1
            new_hi_if_lo = (
                _pct_from((a, a), records_tied) if b1 == a
                else _pct_from((a, b1), records_hi)
            )
        elif kind == 'lo':
            new_hi_if_lo = 0.0 if a + 1 == 4 else _pct_from((a + 1, b), records_lo)
        else:  # tied
            new_hi_if_lo = 0.0 if a + 1 == 4 else _pct_from((a + 1, a), records_lo)

        rec = rec_map.get(state, {})
        rows.append({
            "State"                : _state_label(kind, a, b),
            "N"                    : total,
            "Higher Seed Win%"     : _fmt(hi_pct),
            "Lower Seed Win%"      : _fmt(lo_pct),
            "Swing if Higher Wins" : _swing_str(new_hi_if_hi, hi_pct),
            "Swing if Lower Wins"  : _swing_str(hi_pct, new_hi_if_lo),
            "Last Higher Seed Win" : _recent(rec.get("higher")),
            "Last Lower Seed Win"  : _recent(rec.get("lower")),
        })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    all_series = load_or_fetch_all_series()

    by_length = {}
    for s in all_series:
        by_length[s["num_games"]] = by_length.get(s["num_games"], 0) + 1
    breakdown = "  ".join(f"{g}-game: {n}" for g, n in sorted(by_length.items()))
    print(f"\nTotal series: {len(all_series)}  ({breakdown})\n")

    records_hi, records_lo, records_tied, recency_hi, recency_lo, recency_tied = (
        build_state_records(all_series)
    )
    table = build_output_table(records_hi, records_lo, records_tied,
                               recency_hi, recency_lo, recency_tied)

    header = (
        f"=== NBA Playoff Win Probability by Series State ===\n"
        f"    All best-of-7 series | Seasons {START_YEAR}-{END_YEAR}\n\n"
        f"  Higher Seed Win%      = historical win% for the higher seed from this state\n"
        f"  Lower Seed Win%       = 100% - Higher Seed Win%\n"
        f"  Swing if Higher Wins  = change in Higher Seed Win% if they win the next game\n"
        f"  Swing if Lower Wins   = change in Higher Seed Win% if the lower seed wins next\n"
        f"  Last Higher/Lower Win = most recent series won from that state by each side\n"
        f"\n  Non-tied states appear as two rows: higher seed leading, then lower seed leading.\n"
        f"  team_a (home team in game 1) is treated as the higher seed.\n"
    )
    print(header)
    print(table.to_string(index=False))
    print()


if __name__ == "__main__":
    main()
