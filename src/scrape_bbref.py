"""
Scraper for basketball-reference.com playoff data.

Primary use: pre-1997 seasons (outside nba_api coverage).
Also usable for cross-validation against nba_api results.

Respects basketball-reference's self-imposed rate limit of 20 req/min.
"""

import time
import warnings
import requests
import pandas as pd
from bs4 import BeautifulSoup, Comment

_BASE_URL = "https://www.basketball-reference.com"
_REQ_DELAY = 3.5  # seconds between requests (~17 req/min, safely under 20)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def _get_page(url: str) -> BeautifulSoup:
    time.sleep(_REQ_DELAY)
    resp = requests.get(url, headers=_HEADERS, timeout=15)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def _extract_commented_tables(soup: BeautifulSoup) -> dict[str, BeautifulSoup]:
    """
    Basketball-reference embeds some tables inside HTML comments.
    Returns a dict of {table_id: Tag} for all tables found in comments.
    """
    tables = {}
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        inner = BeautifulSoup(comment, "html.parser")
        for table in inner.find_all("table", id=True):
            tables[table["id"]] = table
    return tables


def fetch_series_results(season_end_year: int) -> pd.DataFrame:
    """
    Scrapes the NBA playoffs summary page for a given season and returns
    game-level results for all playoff series.

    URL pattern: https://www.basketball-reference.com/playoffs/NBA_YYYY.html

    Returns columns: series_label, game_num, date, home_team, away_team,
                     home_pts, away_pts, winner, loser
    """
    url = f"{_BASE_URL}/playoffs/NBA_{season_end_year}.html"
    soup = _get_page(url)

    # The main schedule/results table is usually in comments on this page
    commented = _extract_commented_tables(soup)
    schedule_table = commented.get("schedule") or soup.find("table", id="schedule")

    if schedule_table is None:
        raise ValueError(
            f"Could not find schedule table on {url}. "
            "The page structure may have changed."
        )

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = pd.read_html(str(schedule_table))[0]

    # Drop header-repeat rows basketball-reference sometimes injects
    df = df[df.iloc[:, 0] != df.columns[0]].copy()

    # Column names vary by year; normalize common patterns
    col_map = {}
    for col in df.columns:
        cl = str(col).lower()
        if "date" in cl:
            col_map[col] = "date"
        elif "visitor" in cl or "away" in cl:
            col_map[col] = "away_team"
        elif "home" in cl:
            col_map[col] = "home_team"
        elif cl in ("pts", "visitor pts", "away pts"):
            col_map[col] = "away_pts"
        elif "home pts" in cl or "home.1" in cl:
            col_map[col] = "home_pts"

    df = df.rename(columns=col_map)

    needed = {"date", "away_team", "home_team"}
    missing = needed - set(df.columns)
    if missing:
        raise ValueError(f"Missing expected columns after normalization: {missing}. Got: {list(df.columns)}")

    df = df.dropna(subset=["home_team", "away_team"])
    df["home_pts"] = pd.to_numeric(df.get("home_pts"), errors="coerce")
    df["away_pts"] = pd.to_numeric(df.get("away_pts"), errors="coerce")

    df["winner"] = df.apply(
        lambda r: r["home_team"] if r["home_pts"] > r["away_pts"] else r["away_team"],
        axis=1,
    )
    df["loser"] = df.apply(
        lambda r: r["away_team"] if r["home_pts"] > r["away_pts"] else r["home_team"],
        axis=1,
    )
    df["season"] = season_end_year

    return df[["season", "date", "home_team", "away_team", "home_pts", "away_pts", "winner", "loser"]]


def build_series_winners(season_end_year: int) -> pd.DataFrame:
    """
    Derives series-level winners/losers by aggregating game results.

    Groups games by (home_team, away_team) matchup — assumes each unique
    matchup pair represents one series. Returns one row per series.
    """
    games = fetch_series_results(season_end_year)

    records = []
    # Normalize matchup key so team order doesn't create duplicate groups
    games["matchup_key"] = games.apply(
        lambda r: tuple(sorted([r["home_team"], r["away_team"]])), axis=1
    )

    for key, grp in games.groupby("matchup_key"):
        win_counts = grp["winner"].value_counts()
        team_a, team_b = key
        a_wins = int(win_counts.get(team_a, 0))
        b_wins = int(win_counts.get(team_b, 0))
        series_winner = team_a if a_wins > b_wins else team_b
        series_loser = team_b if series_winner == team_a else team_a

        records.append(
            {
                "season": season_end_year,
                "team_a": team_a,
                "team_b": team_b,
                "team_a_wins": a_wins,
                "team_b_wins": b_wins,
                "series_winner": series_winner,
                "series_loser": series_loser,
                "games_played": len(grp),
            }
        )

    return pd.DataFrame(records)


def _classify_round(header_text: str) -> int:
    """
    Maps a BBref section header (e.g. 'Eastern Conference Finals') to a
    round number 1-4, or 0 if unrecognised.

    BBref presents rounds newest-first (Finals → Conf Finals → Semis → R1),
    so we detect by keyword rather than order.
    """
    t = header_text.lower()
    # NBA/BAA Finals — no "conference" or "division" qualifier, and not "semifinal"
    if "final" in t and "conference" not in t and "division" not in t and "semi" not in t:
        return 4
    if "championship" in t and "conference" not in t and "division" not in t:
        return 4
    # Conference/Division Finals (one step before the championship)
    if ("conference final" in t or "division final" in t) and "semi" not in t:
        return 3
    # Semifinals / Second Round
    if "semifinal" in t or "second round" in t:
        return 2
    # First Round / Quarterfinals
    if "first round" in t or "quarterfinal" in t or "opening round" in t:
        return 1
    return 0


def build_playoff_games_bbref(season_end_year: int) -> pd.DataFrame:
    """
    Scrapes the BBref playoffs page (table id='all_playoffs') and returns
    game-level data in the same format as fetch_playoffs.build_playoff_games().

    BBref's all_playoffs table structure (one block per series):
      - 3-cell header row: [round label, "TeamA over TeamB", "Series Stats"]
      - 1-cell toggleable summary row  (skipped)
      - 6-cell game rows: [Game N, date, away_team, away_pts, "@ home_team", home_pts]

    Groups games into series by canonical (sorted) team-pair.  Each pair
    plays exactly one series per season in the NBA playoffs.
    Assigns game_num by row order within each series block (already chronological).

    series_id format: B{year}{round_digit}{idx:02d}
      round_digit: 1 = R1, 2 = R2, 3 = CF, 4 = F, 0 = unknown
    Columns: game_id, date, series_id, game_num, home_team, away_team,
             home_pts, away_pts, winner, loser
    """
    url = f"{_BASE_URL}/playoffs/NBA_{season_end_year}.html"
    soup = _get_page(url)

    tbl = soup.find("table", id="all_playoffs")
    if tbl is None:
        raise ValueError(f"No 'all_playoffs' table on {url}")

    tbody = tbl.find("tbody")
    if tbody is None:
        raise ValueError(f"all_playoffs table has no <tbody> on {url}")

    games = []
    current_round = 0

    for tr in tbody.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        n = len(cells)

        # 3-cell header: identifies the round for the series block that follows
        if n == 3:
            current_round = _classify_round(cells[0].get_text(strip=True))
            continue

        # 6-cell game row: [Game N, date, away_team, away_pts, "@ home_team", home_pts]
        if n != 6:
            continue
        game_label = cells[0].get_text(strip=True)
        if not game_label.startswith("Game "):
            continue

        date_str   = cells[1].get_text(strip=True)
        away_team  = cells[2].get_text(strip=True)
        away_pts_s = cells[3].get_text(strip=True)
        home_raw   = cells[4].get_text(strip=True)  # "@ Home Team Name"
        home_pts_s = cells[5].get_text(strip=True)

        # Strip "@ " prefix from home team name
        home_team = home_raw[2:] if home_raw.startswith("@ ") else home_raw.lstrip("@ ")

        if not away_team or not home_team:
            continue

        try:
            home_pts = int(float(home_pts_s))
            away_pts = int(float(away_pts_s))
        except (TypeError, ValueError):
            continue

        winner = home_team if home_pts > away_pts else away_team
        loser  = away_team if home_pts > away_pts else home_team

        games.append({
            "round":     current_round,
            "date":      date_str,
            "home_team": home_team,
            "away_team": away_team,
            "home_pts":  home_pts,
            "away_pts":  away_pts,
            "winner":    winner,
            "loser":     loser,
        })

    if not games:
        raise ValueError(f"No game data found for {season_end_year}")

    df = pd.DataFrame(games)
    df["_row"] = range(len(df))
    df["_pair"] = df.apply(
        lambda r: tuple(sorted([r["home_team"], r["away_team"]])), axis=1
    )

    records = []
    series_idx = 0
    for pair, grp in df.groupby("_pair", sort=False):
        rnd = grp["round"].iloc[0]
        sid = f"B{season_end_year}{rnd}{series_idx:02d}"
        series_idx += 1
        for gn, (_, row) in enumerate(grp.sort_values("_row").iterrows(), 1):
            records.append({
                "game_id":   f"{sid}G{gn:02d}",
                "date":      row["date"],
                "series_id": sid,
                "game_num":  gn,
                "home_team": row["home_team"],
                "away_team": row["away_team"],
                "home_pts":  row["home_pts"],
                "away_pts":  row["away_pts"],
                "winner":    row["winner"],
                "loser":     row["loser"],
            })

    return pd.DataFrame(records)


if __name__ == "__main__":
    import sys

    year = int(sys.argv[1]) if len(sys.argv) > 1 else 2025

    print(f"\n=== {year} Playoff Games (basketball-reference) ===")
    games_df = build_playoff_games_bbref(year)
    print(games_df.to_string(index=False))
