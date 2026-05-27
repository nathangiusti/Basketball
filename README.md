# NBA Playoff Series Win Probability

Historical win probability for every possible NBA best-of-7 series state,
computed from all playoff series 1997–2025 (n = 360).

---

## Quick start

```bash
pip install -r requirements.txt

# 1. (First run only) Fetch and cache all season data — takes ~90 s
python src/series_win_probability.py

# 2. Generate index.html from the cached data
python src/generate_webpage.py

# 3. Open index.html in any browser
```

After the first run, re-running either script takes ~2 seconds because all
season data is cached locally in `data/playoff_seasons_cache.pkl`.

---

## Scripts and data flow

```
nba_api (NBA.com)
      │
      ▼
src/fetch_playoffs.py          — low-level API wrappers
      │
      ▼
data/playoff_seasons_cache.pkl — per-season game DataFrames cached to disk
      │
      ▼
src/series_win_probability.py  — filters to best-of-7 series, computes
      │                          state probabilities, prints a text table
      ▼
src/generate_webpage.py        — calls the same logic, renders index.html
      │
      ▼
index.html                     — self-contained browser UI
```

### src/fetch_playoffs.py

Wraps two NBA.com endpoints via `nba_api`:

| Endpoint | What it provides |
|---|---|
| `LeagueGameFinder` | Per-team game rows with W/L outcome |
| `CommonPlayoffSeries` | `SERIES_ID` and `GAME_NUM` per game |

`build_playoff_games(year)` joins both and returns one row per game with
columns: `game_id, date, series_id, game_num, home_team, away_team,
home_pts, away_pts, winner, loser`.

### data/playoff_seasons_cache.pkl

Stores `{year: games_df}` for every season that has been fetched.
The cache is raw (unfiltered), so changing the series-length filter
(e.g. switching from "all best-of-7" to "Finals only") never requires
re-fetching from the API.

### src/series_win_probability.py

Core logic. Key steps:

1. **Load cache** — reads `playoff_seasons_cache.pkl`, fetches any
   missing seasons from the API.

2. **Filter to best-of-7 series** — keeps groups with 4–7 games and
   exactly 2 unique teams. The 2-team check removes corrupted pre-2002
   series IDs that bundled multiple matchups together.

3. **Build state records** — for each game in each series, records the
   series state *before* that game as `(leader_wins, trailer_wins)`.
   - Non-tied states: normalized so `a ≥ b`; `a` = leader's wins.
   - Tied states: tracked from the home-team-in-game-1 (higher seed)
     perspective.

4. **Compute probabilities** — from the counts above:
   - Non-tied: leader win% = wins / total at that state.
   - Tied: home-team win% = wins / total at that state.
   - Swing = (win% in next state) − (current win%).
     For non-tied → tied transitions, the symmetric 50% baseline is used
     for the newly-tied state because neither team has a state-based
     advantage.

5. **Track recency** — for each state, the most recent series in which
   the leader/home team won and the most recent in which the
   trailer/away team won, including the playoff round abbreviation
   extracted from the series ID: `(1)` R1, `(2)` R2, `(CF)` Conf.
   Finals, `(F)` NBA Finals.

### src/generate_webpage.py

Calls `load_or_fetch_all_series` and `build_state_records`, computes
the same probability values, serialises them to JSON, and injects them
into an HTML template. The output `index.html` is fully self-contained
— no server or network access required to use it.

---

## Tied-state interpretation

For tied states (0–0, 1–1, 2–2, 3–3) there is no "leader". Probabilities
are shown from the **higher-seed (home court)** team's perspective:

- The win% shown is the historical rate at which the higher seed has won
  the series from that state (e.g. 73.6% for 0–0 — the higher seed wins
  roughly 3 in 4 series).
- Swing values show how that percentage changes if the home team wins
  the next game vs. if the away team wins.

For non-tied states, win% and swing are from the generic **current leader's**
perspective.

---

## Data sources

- **Primary:** `nba_api` (pip), hitting NBA.com's unofficial stats API.
  Coverage starts 1996–97. No scraping; returns clean JSON.
- **Fallback:** `src/scrape_bbref.py` — direct basketball-reference.com
  scraper for pre-1997 data or cross-validation. Rate-limited to
  ≈17 req/min (3.5 s delay). Not used in the default pipeline.

---

## Files

```
index.html                     ← generated webpage (open in browser)
requirements.txt
README.md
src/
  fetch_playoffs.py            ← nba_api wrappers
  series_win_probability.py    ← probability computation + text table
  generate_webpage.py          ← generates index.html
  scrape_bbref.py              ← bbref fallback scraper (unused by default)
data/
  playoff_seasons_cache.pkl    ← auto-generated cache (git-ignored)
```
