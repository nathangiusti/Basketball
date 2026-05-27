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
    Returns:
      records  – dict: (a_wins, b_wins) -> [led_team_won_count, total_count]
      recency  – dict: (a_wins, b_wins) -> {'leader': (season, winner, loser, round),
                                             'trailer': (season, winner, loser, round)}
                 Most-recent series in which the leader / trailer won from that state.

    Non-tied states (a > b): a = leader wins, b = trailer wins.
    Tied states (a == b):    tracked from team_a perspective (home team in game 1).

    For each game in each series, the state *before* that game is recorded.
    """
    records = defaultdict(lambda: [0, 0])
    recency  = {}          # state -> {'leader': (...), 'trailer': (...)}

    # Sort by season ascending so later entries overwrite earlier ones (keeping most recent)
    for series in sorted(all_series, key=lambda s: s["season"]):
        games      = series["games"]
        team_a     = series["team_a"]
        team_b     = series["team_b"]
        team_a_won = series["team_a_won"]
        season     = series["season"]
        series_id  = series["series_id"]
        winner_team  = series["series_winner"]
        loser_team   = team_b if team_a_won else team_a
        rnd          = _round_abbr(series_id)

        ta_wins = 0
        tb_wins = 0

        for _, game in games.iterrows():
            a, b = ta_wins, tb_wins

            if a > b:
                state      = (a, b)
                leader_won = team_a_won
            elif b > a:
                state      = (b, a)
                leader_won = not team_a_won
            else:
                state      = (a, b)
                leader_won = team_a_won

            records[state][1] += 1
            if leader_won:
                records[state][0] += 1

            # Track most-recent series where leader/trailer won from this state
            rec = recency.setdefault(state, {"leader": None, "trailer": None})
            entry = (season, winner_team, loser_team, rnd)
            if leader_won:
                rec["leader"] = entry
            else:
                rec["trailer"] = entry

            if game["winner"] == team_a:
                ta_wins += 1
            else:
                tb_wins += 1

    return records, recency


def _pct(state, records):
    won, total = records.get(state, [0, 0])
    return (won / total * 100) if total > 0 else None


def _display_pct(a, b, records):
    """
    Win% to show in the table for the 'leader' column.

    Tied states use 50% — by symmetry neither team has an inherent advantage
    from the series state alone. Non-tied states use the historical leader win%.
    """
    if a == b:
        return 50.0
    return _pct((a, b), records)


def _pct_after_leader_wins(a, b, records):
    """Win% for the current leader after they win (state: a+1, b)."""
    if a + 1 == 4:
        return 100.0
    # a+1 > b always, so the new state is never tied — use historical leader win%
    return _pct((a + 1, b), records)


def _pct_after_trailer_wins(a, b, records):
    """
    Win% for the *current leader* after the trailer wins (state: a vs b+1).

    Cases:
      b+1 == 4   → series over, leader loses → 0%
      b+1 >  a   → only when a==b (tied); trailer becomes new leader
      b+1 == a   → newly tied → 50% by symmetry
      b+1 <  a   → leader still leads (by less)
    """
    b1 = b + 1
    if b1 == 4:
        return 0.0
    if b1 > a:
        # Only reachable from a tied state (a==b); trailer with b1 wins now leads
        pct = _pct((b1, a), records)
        return (100.0 - pct) if pct is not None else None
    if b1 == a:
        # Series reaches a tied state — 50% for either team by symmetry
        return 50.0
    # Leader still ahead
    return _pct((a, b1), records)


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


def _label(a, b):
    if a == b:
        return "0-0 (Start)" if a == 0 else f"Tied  {a}-{b}"
    return f"Leads {a}-{b}"


def _fmt(v, *, sign=False):
    if v is None:
        return "N/A"
    if sign:
        return f"+{v:.1f}%" if v >= 0 else f"{v:.1f}%"
    return f"{v:.1f}%"


def _recent(entry):
    """Format a recency entry (season, winner, loser, round) as a short string."""
    if entry is None:
        return "N/A"
    season, winner, loser, *rest = entry
    rnd = rest[0] if rest else ''
    suffix = f" {rnd}" if rnd else ''
    return f"{season} {winner} over {loser}{suffix}"


def build_output_table(records, recency):
    rows = []
    for (a, b) in ALL_STATES:
        pct        = _display_pct(a, b, records)
        raw_pct    = _pct((a, b), records)
        won, total = records.get((a, b), [0, 0])

        new_lw = _pct_after_leader_wins(a, b, records)
        new_tw = _pct_after_trailer_wins(a, b, records)

        swing_lw = (new_lw - pct) if (pct is not None and new_lw is not None) else None
        swing_tw = (new_tw - pct) if (pct is not None and new_tw is not None) else None

        leader_col = _fmt(pct)
        if a == b and raw_pct is not None:
            leader_col += f"  (home: {raw_pct:.1f}%)"

        rec = recency.get((a, b), {})
        rows.append({
            "State"                  : _label(a, b),
            "N"                      : total,
            "Leader Win%"            : leader_col,
            "Trailer Win%"           : _fmt(100 - pct if pct is not None else None),
            "Swing if Leader Wins"   : _fmt(swing_lw, sign=True),
            "Swing if Trailer Wins"  : _fmt(swing_tw, sign=True),
            "Last Leader Win"        : _recent(rec.get("leader")),
            "Last Trailer Win"       : _recent(rec.get("trailer")),
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

    records, recency = build_state_records(all_series)
    table = build_output_table(records, recency)

    header = (
        f"=== NBA Playoff Win Probability by Series State ===\n"
        f"    All best-of-7 series | Seasons {START_YEAR}-{END_YEAR}\n\n"
        f"  Leader Win%           = win% for the team currently ahead\n"
        f"                          Tied states show 50% (symmetric by state alone);\n"
        f"                          '(home: X%)' is the historical rate for the\n"
        f"                          home team in game 1 (typically the higher seed)\n"
        f"  Trailer Win%          = 100% - Leader Win%\n"
        f"  Swing if Leader Wins  = change in Leader Win% if they win the next game\n"
        f"  Swing if Trailer Wins = change in Leader Win% if the trailer wins the next game\n"
        f"  Last Leader/Trailer Win = most recent series won from that state by each side\n"
    )
    print(header)
    print(table.to_string(index=False))
    print()


if __name__ == "__main__":
    main()
