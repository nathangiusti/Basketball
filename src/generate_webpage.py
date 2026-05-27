"""
Generates index.html from the series probability data.

Run this script (not series_win_probability.py) to refresh the webpage:
    python src/generate_webpage.py

Reads:  data/playoff_seasons_cache.pkl  (auto-fetches from nba_api if absent)
Writes: index.html  (project root)
"""

import json
import os
import sys
from collections import defaultdict

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SRC_DIR)
sys.path.insert(0, _SRC_DIR)

from series_win_probability import (
    load_or_fetch_all_series,
    _round_abbr,
    ALL_STATES,
    START_YEAR,
    END_YEAR,
)

OUTPUT_PATH = os.path.join(_PROJECT_ROOT, "index.html")


# ---------------------------------------------------------------------------
# Data computation
# ---------------------------------------------------------------------------

def _round_num(series_id):
    """Returns integer round (0-4) from a series_id; 0 = unknown."""
    s = str(series_id)
    if s.startswith('B'):
        return int(s[5]) if len(s) >= 7 and s[5].isdigit() else 0
    return int(s[7]) if len(s) >= 8 and s[7].isdigit() and s[7] != '0' else 0


def build_js_data(all_series):
    """
    Builds per-state, per-round stats for JS-side filtering.

    Tied states:     { tied:true,  byRound:{...} }
    Non-tied states: { tied:false, home:{byRound:{...}}, away:{byRound:{...}} }

    'home' = higher seed (team_a, home in game 1) is currently leading
    'away' = lower seed  (team_b, away in game 1) is currently leading
    """
    records_tied = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    recency_tied = defaultdict(lambda: defaultdict(lambda: {"leader": None, "trailer": None}))
    records_home = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    recency_home = defaultdict(lambda: defaultdict(lambda: {"leader": None, "trailer": None}))
    records_away = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    recency_away = defaultdict(lambda: defaultdict(lambda: {"leader": None, "trailer": None}))

    for series in sorted(all_series, key=lambda s: s["season"]):
        games      = series["games"]
        team_a     = series["team_a"]
        team_b     = series["team_b"]
        team_a_won = series["team_a_won"]
        season     = series["season"]
        series_id  = series["series_id"]
        winner     = series["series_winner"]
        loser      = team_b if team_a_won else team_a
        rnd        = _round_num(series_id)
        rnd_str    = _round_abbr(series_id)
        suffix     = f" {rnd_str}" if rnd_str else ""
        entry      = (season, f"{season} {winner} over {loser}{suffix}")

        ta_wins = tb_wins = 0
        for _, game in games.iterrows():
            a, b = ta_wins, tb_wins

            if a > b:
                state      = (a, b)
                leader_won = team_a_won
                recs       = records_home
                rec_map    = recency_home
            elif b > a:
                state      = (b, a)
                leader_won = not team_a_won
                recs       = records_away
                rec_map    = recency_away
            else:
                state      = (a, b)
                leader_won = team_a_won
                recs       = records_tied
                rec_map    = recency_tied

            recs[rnd][state][1] += 1
            if leader_won:
                recs[rnd][state][0] += 1

            rec = rec_map[rnd][state]
            if leader_won:
                rec["leader"] = entry
            else:
                rec["trailer"] = entry

            if game["winner"] == team_a:
                ta_wins += 1
            else:
                tb_wins += 1

    def make_by_round(recs, recency, state):
        out = {}
        for rnd in range(5):
            won, total = recs[rnd].get(state, [0, 0])
            rec = recency[rnd].get(state, {})
            ll  = rec.get("leader")
            lt  = rec.get("trailer")
            out[str(rnd)] = {
                "won": won, "total": total,
                "lastL":       ll[1] if ll else None,
                "lastLSeason": ll[0] if ll else 0,
                "lastT":       lt[1] if lt else None,
                "lastTSeason": lt[0] if lt else 0,
            }
        return out

    result = {}
    for (a, b) in ALL_STATES:
        tied = (a == b)
        key  = f"{a}-{b}"

        if tied:
            result[key] = {
                "tied":    True,
                "byRound": make_by_round(records_tied, recency_tied, (a, b)),
            }
        else:
            result[key] = {
                "tied": False,
                "home": {"byRound": make_by_round(records_home, recency_home, (a, b))},
                "away": {"byRound": make_by_round(records_away, recency_away, (a, b))},
            }

    return result


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

def build_html(data_dict, total_series, start_year, end_year):
    data_json = json.dumps(data_dict, indent=2)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>NBA Playoff Series Win Probability</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: #0d0d1a;
      color: #dde0f0;
      min-height: 100vh;
    }}

    /* Header */
    .site-header {{
      background: linear-gradient(135deg, #151530 0%, #1e1040 100%);
      border-bottom: 3px solid #f4873a;
      padding: 1.75rem 1rem;
      text-align: center;
    }}
    .site-header h1 {{
      font-size: clamp(1.3rem, 4vw, 1.9rem);
      font-weight: 800;
      color: #f4873a;
    }}
    .site-header p {{ color: #8888b0; margin-top: 0.4rem; font-size: 0.88rem; }}

    /* Layout */
    .page {{ max-width: 1200px; margin: 2rem auto; padding: 0 1rem 3rem; }}

    /* Cards */
    .card {{
      background: #151530;
      border: 1px solid #25255a;
      border-radius: 14px;
      padding: 1.75rem;
      margin-bottom: 1.5rem;
    }}

    /* Round filter */
    .filter-row {{
      display: flex; align-items: center; gap: 1.25rem;
      flex-wrap: wrap; margin-bottom: 1rem;
    }}
    .filter-label {{
      font-size: 0.72rem; text-transform: uppercase;
      letter-spacing: 0.09em; color: #55558a; white-space: nowrap;
    }}
    .round-label {{
      font-size: 0.875rem; color: #b0b0cc;
      display: flex; align-items: center; gap: 0.4rem;
      cursor: pointer; user-select: none;
    }}
    .round-label input[type="checkbox"] {{
      accent-color: #f4873a; width: 15px; height: 15px; cursor: pointer;
    }}
    .round-label:hover {{ color: #dde0f0; }}

    /* Reference table */
    .table-title {{ font-size: 1rem; font-weight: 700; color: #f4873a; margin-bottom: 0.75rem; }}
    .table-note {{ font-size: 0.78rem; color: #55558a; margin-bottom: 1rem; line-height: 1.5; }}
    .table-scroll {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; white-space: nowrap; }}
    thead th {{
      text-align: left; padding: 0.5rem 0.7rem;
      color: #55558a; font-size: 0.7rem;
      text-transform: uppercase; letter-spacing: 0.06em;
      border-bottom: 1px solid #20204a;
    }}
    tbody td {{ padding: 0.55rem 0.7rem; border-bottom: 1px solid #151535; }}
    tbody tr:hover td {{ background: #0f0f28; }}
    tbody tr.away-row td {{ background: #0d0d20; }}
    tbody tr.away-row:hover td {{ background: #0f0f2a; }}
    .c-l {{ color: #2ecc71; }}
    .c-t {{ color: #e74c3c; }}
    .c-n {{ color: #8888b0; }}
    .seed-badge {{
      display: inline-block;
      font-size: 0.65rem; font-weight: 700;
      padding: 0.1rem 0.35rem; border-radius: 3px;
      margin-right: 0.3rem; vertical-align: middle;
    }}
    .badge-home {{ background: #1a3a2a; color: #2ecc71; }}
    .badge-away {{ background: #3a1a1a; color: #e74c3c; }}

    @media (max-width: 520px) {{
      .filter-row {{ gap: 0.75rem; }}
    }}
  </style>
</head>
<body>

<header class="site-header">
  <h1>NBA Playoff Series Win Probability</h1>
  <p>Historical win rates by series state &mdash; all best-of-7 series, {start_year}&ndash;{end_year} (n&nbsp;=&nbsp;{total_series:,})</p>
</header>

<main class="page">

  <!-- Reference table -->
  <div class="card">
    <div class="table-title">All Series States &mdash; Reference Table</div>
    <div class="filter-row">
      <span class="filter-label">Rounds:</span>
      <label class="round-label"><input class="round-cb" type="checkbox" value="1" checked onchange="onRoundChange()"> 1st Round</label>
      <label class="round-label"><input class="round-cb" type="checkbox" value="2" checked onchange="onRoundChange()"> 2nd Round</label>
      <label class="round-label"><input class="round-cb" type="checkbox" value="3" checked onchange="onRoundChange()"> Conf. Finals</label>
      <label class="round-label"><input class="round-cb" type="checkbox" value="4" checked onchange="onRoundChange()"> Finals</label>
    </div>
    <p class="table-note">
      Non-tied states are split by whether the higher seed or lower seed is leading.
      Win% shown for the current leader; tied states show the higher seed's historical win rate.
      Swing = change in the leader's win% if either team wins the next game.
    </p>
    <div class="table-scroll">
      <table>
        <thead>
          <tr>
            <th>State</th>
            <th>N</th>
            <th>Leader Win%</th>
            <th>Trailer Win%</th>
            <th>If Leader Wins</th>
            <th>If Trailer Wins</th>
            <th>Last Leader Win</th>
            <th>Last Trailer Win</th>
          </tr>
        </thead>
        <tbody id="tBody"></tbody>
      </table>
    </div>
  </div>

</main>

<script>
const DATA = {data_json};

const TABLE_ROWS = [
  {{ key:'0-0', label:'0-0 (Start)',           sub:null   }},
  {{ key:'1-0', label:'Higher seed leads 1-0', sub:'home' }},
  {{ key:'1-0', label:'Lower seed leads 0-1',  sub:'away' }},
  {{ key:'1-1', label:'Tied 1-1',              sub:null   }},
  {{ key:'2-0', label:'Higher seed leads 2-0', sub:'home' }},
  {{ key:'2-0', label:'Lower seed leads 0-2',  sub:'away' }},
  {{ key:'2-1', label:'Higher seed leads 2-1', sub:'home' }},
  {{ key:'2-1', label:'Lower seed leads 1-2',  sub:'away' }},
  {{ key:'2-2', label:'Tied 2-2',              sub:null   }},
  {{ key:'3-0', label:'Higher seed leads 3-0', sub:'home' }},
  {{ key:'3-0', label:'Lower seed leads 0-3',  sub:'away' }},
  {{ key:'3-1', label:'Higher seed leads 3-1', sub:'home' }},
  {{ key:'3-1', label:'Lower seed leads 1-3',  sub:'away' }},
  {{ key:'3-2', label:'Higher seed leads 3-2', sub:'home' }},
  {{ key:'3-2', label:'Lower seed leads 2-3',  sub:'away' }},
  {{ key:'3-3', label:'Tied 3-3',              sub:null   }},
];

let selectedRounds = new Set([1, 2, 3, 4]);

// ---- Round-filtered stat helpers ----

function getStateStats(key, sub) {{
  const d = DATA[key];
  const byRound = sub ? d[sub].byRound : d.byRound;
  let won = 0, total = 0;
  let lastL = null, lastLSeason = 0;
  let lastT = null, lastTSeason = 0;
  for (const rnd of [0, ...selectedRounds]) {{
    const r = byRound[String(rnd)];
    if (!r || r.total === 0) continue;
    won   += r.won;
    total += r.total;
    if (r.lastL && r.lastLSeason > lastLSeason) {{ lastL = r.lastL; lastLSeason = r.lastLSeason; }}
    if (r.lastT && r.lastTSeason > lastTSeason) {{ lastT = r.lastT; lastTSeason = r.lastTSeason; }}
  }}
  const lPct = total > 0 ? +(won / total * 100).toFixed(1) : null;
  return {{ lPct, total, lastL, lastT }};
}}

function getSwings(key, sub) {{
  const {{ lPct }} = getStateStats(key, sub);
  if (lPct === null) return {{ swL: null, swT: null }};

  const [a, b] = key.split('-').map(Number);
  const tied = DATA[key].tied;
  let newL, newT;

  if (tied) {{
    // Home wins -> home leads (a+1)-a
    newL = (a + 1 === 4) ? 100 : getStateStats(`${{a+1}}-${{a}}`, 'home').lPct;
    // Away wins -> away leads (a+1)-a; from home perspective: 100 - awayLeaderPct
    if (a + 1 === 4) {{
      newT = 0;
    }} else {{
      const np = getStateStats(`${{a+1}}-${{a}}`, 'away').lPct;
      newT = np !== null ? +(100 - np).toFixed(1) : null;
    }}
  }} else {{
    // Leader wins -> same sub, incremented
    newL = (a + 1 === 4) ? 100 : getStateStats(`${{a+1}}-${{b}}`, sub).lPct;
    const b1 = b + 1;
    if (b1 === 4) {{
      newT = 0;
    }} else if (b1 === a) {{
      // Newly tied: use historical tied-state win% for the home team
      const tiedPct = getStateStats(`${{a}}-${{b1}}`, null).lPct;
      newT = sub === 'home' ? tiedPct : (tiedPct !== null ? +(100 - tiedPct).toFixed(1) : null);
    }} else {{
      // Leader still leading, same sub
      newT = getStateStats(`${{a}}-${{b1}}`, sub).lPct;
    }}
  }}

  return {{
    swL: (newL !== null && lPct !== null) ? +(newL - lPct).toFixed(1) : null,
    swT: (newT !== null && lPct !== null) ? +(newT - lPct).toFixed(1) : null,
  }};
}}

// ---- Filter change handler ----

function onRoundChange() {{
  selectedRounds = new Set();
  document.querySelectorAll('.round-cb:checked').forEach(cb => {{
    selectedRounds.add(Number(cb.value));
  }});
  buildTable();
}}

function buildTable() {{
  const tbody = el('tBody');
  tbody.innerHTML = '';
  TABLE_ROWS.forEach(({{ key, label, sub }}) => {{
    const {{ lPct, total, lastL, lastT }} = getStateStats(key, sub);
    const {{ swL, swT }} = getSwings(key, sub);
    const tPct   = lPct !== null ? +(100 - lPct).toFixed(1) : null;
    const slCls  = swL === null ? 'c-n' : (swL > 0 ? 'c-l' : swL < 0 ? 'c-t' : 'c-n');
    const stCls  = swT === null ? 'c-n' : (swT > 0 ? 'c-l' : swT < 0 ? 'c-t' : 'c-n');
    const isAway = sub === 'away';
    const badge  = sub
      ? `<span class="seed-badge ${{isAway ? 'badge-away' : 'badge-home'}}">${{isAway ? 'LO' : 'HI'}}</span>`
      : '';
    const tr = document.createElement('tr');
    if (isAway) tr.classList.add('away-row');
    tr.innerHTML = `
      <td>${{badge}}${{label}}</td>
      <td class="c-n">${{total}}</td>
      <td class="c-l">${{fmt(lPct)}}</td>
      <td class="c-t">${{tPct !== null ? tPct.toFixed(1) + '%' : 'N/A'}}</td>
      <td class="${{slCls}}">${{fmtSw(swL)}}</td>
      <td class="${{stCls}}">${{fmtSw(swT)}}</td>
      <td>${{lastL || 'N/A'}}</td>
      <td>${{lastT || 'N/A'}}</td>
    `;
    tbody.appendChild(tr);
  }});
}}

function el(id)   {{ return document.getElementById(id); }}
function fmt(v)   {{ return v == null ? 'N/A' : v.toFixed(1) + '%'; }}
function fmtSw(v) {{ return v == null ? 'N/A' : (v >= 0 ? '+' : '') + v.toFixed(1) + '%'; }}

buildTable();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    all_series = load_or_fetch_all_series()
    total = len(all_series)

    data_dict = build_js_data(all_series)

    html = build_html(data_dict, total, START_YEAR, END_YEAR)
    html = html.replace("{data_json}", json.dumps(data_dict, indent=2))

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Written: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
