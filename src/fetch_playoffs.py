"""
Fetches NBA playoff game and series results using nba_api (NBA.com stats API).

Coverage: ~1996-97 season onward.
For earlier seasons, use scrape_bbref.py instead.
"""

import time
import pandas as pd
from nba_api.stats.endpoints import CommonPlayoffSeries, LeagueGameFinder


def _format_season(year: int) -> str:
    """Convert end year to NBA season string: 2025 -> '2024-25'."""
    return f"{year - 1}-{str(year)[-2:]}"


def fetch_playoff_games(season_end_year: int) -> pd.DataFrame:
    """
    Returns one row per team per playoff game with win/loss outcome.

    Columns: GAME_ID, GAME_DATE, TEAM_ID, TEAM_ABBREVIATION, TEAM_NAME,
             WL, PTS, OPP_PTS, MATCHUP, SEASON_ID
    """
    season = _format_season(season_end_year)
    time.sleep(0.6)  # stay well under the 20 req/min rate limit

    finder = LeagueGameFinder(
        season_nullable=season,
        season_type_nullable="Playoffs",
        player_or_team_abbreviation="T",
        league_id_nullable="00",
    )
    games = finder.get_data_frames()[0]
    games["SEASON_END_YEAR"] = season_end_year
    return games


def fetch_playoff_series_map(season_end_year: int) -> pd.DataFrame:
    """
    Returns one row per game per series, mapping GAME_ID -> SERIES_ID and round info.

    Columns: GAME_ID, HOME_TEAM_ID, VISITOR_TEAM_ID, SERIES_ID, GAME_NUM
    """
    season = _format_season(season_end_year)
    time.sleep(0.6)

    series_data = CommonPlayoffSeries(
        season=season,
        league_id="00",
    )
    return series_data.get_data_frames()[0]


def build_playoff_games(season_end_year: int) -> pd.DataFrame:
    """
    Produces a clean game-level DataFrame with both teams, scores, and winner/loser.

    Returns one row per game (not per team-game).
    Columns: game_id, season, date, series_id, game_num,
             home_team, away_team, home_pts, away_pts, winner, loser
    """
    raw_games = fetch_playoff_games(season_end_year)
    series_map = fetch_playoff_series_map(season_end_year)

    # Pivot raw_games from team-per-row to game-per-row
    wins = raw_games[raw_games["WL"] == "W"][
        ["GAME_ID", "TEAM_ABBREVIATION", "PTS", "MATCHUP"]
    ].rename(columns={"TEAM_ABBREVIATION": "winner", "PTS": "winner_pts"})

    losses = raw_games[raw_games["WL"] == "L"][
        ["GAME_ID", "TEAM_ABBREVIATION", "PTS", "GAME_DATE"]
    ].rename(columns={"TEAM_ABBREVIATION": "loser", "PTS": "loser_pts"})

    games = wins.merge(losses, on="GAME_ID")

    # Determine home vs away from MATCHUP string (e.g. "BOS vs. MIA" = home, "BOS @ MIA" = away)
    games["home_team"] = games.apply(
        lambda r: r["winner"] if "vs." in r["MATCHUP"] else r["loser"], axis=1
    )
    games["away_team"] = games.apply(
        lambda r: r["loser"] if "vs." in r["MATCHUP"] else r["winner"], axis=1
    )
    games["home_pts"] = games.apply(
        lambda r: r["winner_pts"] if "vs." in r["MATCHUP"] else r["loser_pts"], axis=1
    )
    games["away_pts"] = games.apply(
        lambda r: r["loser_pts"] if "vs." in r["MATCHUP"] else r["winner_pts"], axis=1
    )

    games = games.merge(
        series_map[["GAME_ID", "SERIES_ID", "GAME_NUM"]],
        on="GAME_ID",
        how="left",
    )

    return games[
        [
            "GAME_ID",
            "GAME_DATE",
            "SERIES_ID",
            "GAME_NUM",
            "home_team",
            "away_team",
            "home_pts",
            "away_pts",
            "winner",
            "loser",
        ]
    ].rename(columns={"GAME_ID": "game_id", "GAME_DATE": "date", "SERIES_ID": "series_id", "GAME_NUM": "game_num"})


def build_playoff_series(season_end_year: int) -> pd.DataFrame:
    """
    Produces a series-level DataFrame with the winner and loser of each series.

    Returns one row per series.
    Columns: series_id, season, team_a, team_b, team_a_wins, team_b_wins,
             series_winner, series_loser, games_played
    """
    games = build_playoff_games(season_end_year)

    records = []
    for series_id, grp in games.groupby("series_id"):
        win_counts = grp["winner"].value_counts()
        teams = list(win_counts.index)
        if len(teams) < 2:
            # one team may have swept; loser has 0 wins
            all_teams = set(grp["home_team"]) | set(grp["away_team"])
            teams = list(all_teams)

        team_a, team_b = teams[0], teams[1]
        a_wins = int(win_counts.get(team_a, 0))
        b_wins = int(win_counts.get(team_b, 0))
        series_winner = team_a if a_wins > b_wins else team_b
        series_loser = team_b if series_winner == team_a else team_a

        records.append(
            {
                "series_id": series_id,
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

    return pd.DataFrame(records).sort_values("series_id")


if __name__ == "__main__":
    import sys

    year = int(sys.argv[1]) if len(sys.argv) > 1 else 2025

    print(f"\n=== {_format_season(year)} Playoff Games ===")
    games_df = build_playoff_games(year)
    print(games_df.to_string(index=False))

    print(f"\n=== {_format_season(year)} Playoff Series Results ===")
    series_df = build_playoff_series(year)
    print(series_df.to_string(index=False))
