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
    _abbr,
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

    Returns {'combined': {...}, 'seeded': {...}}

    combined[key] = {tied, byRound} — leader/trailer win%, no seeding distinction
    seeded[key]   = {tied, byRound}              for tied states
                  = {tied, home:{byRound}, away:{byRound}} for non-tied states
      'home' = higher seed (team_a, home in game 1) is leading
      'away' = lower seed  (team_b, away in game 1) is leading
    """
    records_tied = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    recency_tied = defaultdict(lambda: defaultdict(lambda: {"leader": None, "trailer": None}))
    records_home = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    recency_home = defaultdict(lambda: defaultdict(lambda: {"leader": None, "trailer": None}))
    records_away = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    recency_away = defaultdict(lambda: defaultdict(lambda: {"leader": None, "trailer": None}))
    records_comb = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    recency_comb = defaultdict(lambda: defaultdict(lambda: {"leader": None, "trailer": None}))

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
        entry      = (season, f"{season} {_abbr(winner)} over {_abbr(loser)}{suffix}")

        ta_wins = tb_wins = 0
        for _, game in games.iterrows():
            a, b = ta_wins, tb_wins

            # ---- Seeded ----
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

            # ---- Combined (leader-based, no seeding distinction) ----
            if a > b:
                comb_state   = (a, b)
                comb_ldr_won = team_a_won
            elif b > a:
                comb_state   = (b, a)
                comb_ldr_won = not team_a_won
            else:
                comb_state   = (a, b)
                comb_ldr_won = team_a_won

            records_comb[rnd][comb_state][1] += 1
            if comb_ldr_won:
                records_comb[rnd][comb_state][0] += 1
            rec_c = recency_comb[rnd][comb_state]
            if comb_ldr_won:
                rec_c["leader"] = entry
            else:
                rec_c["trailer"] = entry

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

    seeded = {}
    for (a, b) in ALL_STATES:
        tied = (a == b)
        key  = f"{a}-{b}"
        if tied:
            seeded[key] = {
                "tied":    True,
                "byRound": make_by_round(records_tied, recency_tied, (a, b)),
            }
        else:
            seeded[key] = {
                "tied": False,
                "home": {"byRound": make_by_round(records_home, recency_home, (a, b))},
                "away": {"byRound": make_by_round(records_away, recency_away, (a, b))},
            }

    combined = {}
    for (a, b) in ALL_STATES:
        key = f"{a}-{b}"
        combined[key] = {
            "tied":    (a == b),
            "byRound": make_by_round(records_comb, recency_comb, (a, b)),
        }

    return {"combined": combined, "seeded": seeded}


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

    .page {{ max-width: 1200px; margin: 2rem auto; padding: 0 1rem 3rem; }}

    .card {{
      background: #151530;
      border: 1px solid #25255a;
      border-radius: 14px;
      padding: 1.75rem;
      margin-bottom: 1.5rem;
    }}

    .filter-row {{
      display: flex; align-items: center; gap: 1.25rem;
      flex-wrap: wrap; margin-bottom: 1.25rem;
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

    .tab-bar {{
      display: flex; gap: 0;
      border-bottom: 2px solid #25255a;
      margin-bottom: 1.5rem;
    }}
    .tab-btn {{
      background: transparent; color: #8888b0;
      border: none; border-bottom: 3px solid transparent;
      padding: 0.6rem 1.5rem; margin-bottom: -2px;
      cursor: pointer; font-size: 0.9rem; font-weight: 600;
      transition: color 0.15s, border-color 0.15s;
    }}
    .tab-btn:hover {{ color: #dde0f0; }}
    .tab-btn.active {{ color: #f4873a; border-bottom-color: #f4873a; }}
    .tab-panel {{ display: none; }}
    .tab-panel.active {{ display: block; }}

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
      .tab-btn {{ padding: 0.6rem 1rem; font-size: 0.82rem; }}
    }}
  </style>
</head>
<body>

<header class="site-header">
  <h1>NBA Playoff Series Win Probability</h1>
  <p>Historical win rates by series state &mdash; all best-of-7 series, {start_year}&ndash;{end_year} (n&nbsp;=&nbsp;{total_series:,})</p>
</header>

<main class="page">
  <div class="card">

    <!-- Shared round filter -->
    <div class="filter-row">
      <span class="filter-label">Rounds:</span>
      <label class="round-label"><input class="round-cb" type="checkbox" value="1" checked onchange="onRoundChange()"> 1st Round</label>
      <label class="round-label"><input class="round-cb" type="checkbox" value="2" checked onchange="onRoundChange()"> 2nd Round</label>
      <label class="round-label"><input class="round-cb" type="checkbox" value="3" checked onchange="onRoundChange()"> Conf. Finals</label>
      <label class="round-label"><input class="round-cb" type="checkbox" value="4" checked onchange="onRoundChange()"> Finals</label>
    </div>

    <!-- Tab bar -->
    <div class="tab-bar">
      <button class="tab-btn active" data-tab="combined" onclick="switchTab('combined')">No Seeding</button>
      <button class="tab-btn"        data-tab="seeded"   onclick="switchTab('seeded')">By Seeding</button>
    </div>

    <!-- Tab 1: No Seeding -->
    <div id="tab-combined" class="tab-panel active">
      <div class="table-title">Series Win Probability &mdash; All Leaders</div>
      <p class="table-note">
        Win% for whichever team is currently leading, regardless of seeding.
        Tied states show 50% (symmetric by state); <em>(home: X%)</em> is the historical
        rate for the home team in game&nbsp;1. Swing&nbsp;= change in the leader&rsquo;s win% if either team wins the next game.
      </p>
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>State</th><th>N</th><th>Leader Win%</th><th>Trailer Win%</th>
              <th>If Leader Wins</th><th>If Trailer Wins</th>
              <th>Last Leader Win</th><th>Last Trailer Win</th>
            </tr>
          </thead>
          <tbody id="tBodyCombined"></tbody>
        </table>
      </div>
    </div>

    <!-- Tab 2: By Seeding -->
    <div id="tab-seeded" class="tab-panel">
      <div class="table-title">Series Win Probability &mdash; By Seeding</div>
      <p class="table-note">
        Non-tied states are split by whether the higher or lower seed is leading.
        Win% is always from the higher seed&rsquo;s perspective.
        Swing&nbsp;= change in the higher seed&rsquo;s win% if either team wins the next game.
      </p>
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>State</th><th>N</th><th>Higher Seed Win%</th><th>Lower Seed Win%</th>
              <th>If Higher Seed Wins</th><th>If Lower Seed Wins</th>
              <th>Last Higher Seed Win</th><th>Last Lower Seed Win</th>
            </tr>
          </thead>
          <tbody id="tBody"></tbody>
        </table>
      </div>
    </div>

  </div>
</main>

<script>
const DATA = {data_json};

// ---- No-seeding (combined) rows ----
const TABLE_ROWS_COMBINED = [
  {{ key:'0-0', label:'0-0 (Start)'      }},
  {{ key:'1-0', label:'Leader leads 1-0' }},
  {{ key:'1-1', label:'Tied 1-1'         }},
  {{ key:'2-0', label:'Leader leads 2-0' }},
  {{ key:'2-1', label:'Leader leads 2-1' }},
  {{ key:'2-2', label:'Tied 2-2'         }},
  {{ key:'3-0', label:'Leader leads 3-0' }},
  {{ key:'3-1', label:'Leader leads 3-1' }},
  {{ key:'3-2', label:'Leader leads 3-2' }},
  {{ key:'3-3', label:'Tied 3-3'         }},
];

// ---- By-seeding rows ----
const TABLE_ROWS_SEEDED = [
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

// ---- Combined helpers ----

function getCombinedStats(key) {{
  const d = DATA.combined[key];
  const byRound = d.byRound;
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
  const rawPct = total > 0 ? +(won / total * 100).toFixed(1) : null;
  const lPct   = d.tied ? 50.0 : rawPct;
  return {{ lPct, rawPct, total, lastL, lastT }};
}}

function getCombinedSwings(key) {{
  const {{ lPct }} = getCombinedStats(key);
  if (lPct === null) return {{ swL: null, swT: null }};
  const [a, b] = key.split('-').map(Number);
  const tied = DATA.combined[key].tied;
  let newL, newT;
  if (tied) {{
    if (a + 1 === 4) {{ newL = 100; newT = 0; }}
    else {{
      const {{ lPct: np }} = getCombinedStats(`${{a+1}}-${{a}}`);
      newL = np;
      newT = np !== null ? +(100 - np).toFixed(1) : null;
    }}
  }} else {{
    newL = (a + 1 === 4) ? 100 : getCombinedStats(`${{a+1}}-${{b}}`).lPct;
    const b1 = b + 1;
    if      (b1 === 4) newT = 0;
    else if (b1 === a) newT = 50;
    else               newT = getCombinedStats(`${{a}}-${{b1}}`).lPct;
  }}
  return {{
    swL: (newL !== null && lPct !== null) ? +(newL - lPct).toFixed(1) : null,
    swT: (newT !== null && lPct !== null) ? +(newT - lPct).toFixed(1) : null,
  }};
}}

function buildTableCombined() {{
  const tbody = el('tBodyCombined');
  tbody.innerHTML = '';
  TABLE_ROWS_COMBINED.forEach(({{ key, label }}) => {{
    const {{ lPct, rawPct, total, lastL, lastT }} = getCombinedStats(key);
    const {{ swL, swT }} = getCombinedSwings(key);
    const tied    = DATA.combined[key].tied;
    const tPct    = lPct !== null ? +(100 - lPct).toFixed(1) : null;
    // trSwing: show the trailer's gain (negate leader's loss) so "If Trailer Wins" is always positive.
    const trSwing = swT !== null ? +(-swT).toFixed(1) : null;
    const slCls = swL    === null ? 'c-n' : (swL  > 0 ? 'c-l' : swL  < 0 ? 'c-t' : 'c-n');
    const stCls = trSwing === null ? 'c-n' : 'c-l';

    let lPctDisp = fmt(lPct);
    if (tied && rawPct !== null) lPctDisp += ` <span class="c-n">(home: ${{rawPct.toFixed(1)}}%)</span>`;

    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${{label}}</td>
      <td class="c-n">${{total}}</td>
      <td style="color:${{pctColor(lPct)}}">${{lPctDisp}}</td>
      <td style="color:${{pctColor(tPct)}}">${{tPct !== null ? tPct.toFixed(1) + '%' : 'N/A'}}</td>
      <td class="${{slCls}}">${{fmtSw(swL)}}</td>
      <td class="${{stCls}}">${{fmtSw(trSwing)}}</td>
      <td>${{lastL || 'N/A'}}</td>
      <td>${{lastT || 'N/A'}}</td>
    `;
    tbody.appendChild(tr);
  }});
}}

// ---- Seeded helpers ----

function getStateStats(key, sub) {{
  const d = DATA.seeded[key];
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
  const tied = DATA.seeded[key].tied;
  let newL, newT;
  if (tied) {{
    newL = (a + 1 === 4) ? 100 : getStateStats(`${{a+1}}-${{a}}`, 'home').lPct;
    if (a + 1 === 4) {{
      newT = 0;
    }} else {{
      const np = getStateStats(`${{a+1}}-${{a}}`, 'away').lPct;
      newT = np !== null ? +(100 - np).toFixed(1) : null;
    }}
  }} else {{
    newL = (a + 1 === 4) ? 100 : getStateStats(`${{a+1}}-${{b}}`, sub).lPct;
    const b1 = b + 1;
    if (b1 === 4) {{
      newT = 0;
    }} else if (b1 === a) {{
      const tiedPct = getStateStats(`${{a}}-${{b1}}`, null).lPct;
      newT = sub === 'home' ? tiedPct : (tiedPct !== null ? +(100 - tiedPct).toFixed(1) : null);
    }} else {{
      newT = getStateStats(`${{a}}-${{b1}}`, sub).lPct;
    }}
  }}
  return {{
    swL: (newL !== null && lPct !== null) ? +(newL - lPct).toFixed(1) : null,
    swT: (newT !== null && lPct !== null) ? +(newT - lPct).toFixed(1) : null,
  }};
}}

function buildTableSeeded() {{
  const tbody = el('tBody');
  tbody.innerHTML = '';
  TABLE_ROWS_SEEDED.forEach(({{ key, label, sub }}) => {{
    const {{ lPct, total, lastL, lastT }} = getStateStats(key, sub);
    const {{ swL, swT }} = getSwings(key, sub);
    const isAway = sub === 'away';

    const hiPct     = isAway ? (lPct !== null ? +(100 - lPct).toFixed(1) : null) : lPct;
    const loPct     = isAway ? lPct : (lPct !== null ? +(100 - lPct).toFixed(1) : null);
    const hiSwIfHi  = isAway ? (swT !== null ? +(-swT).toFixed(1) : null) : swL;
    // Show the lower seed's gain (= negate the higher seed's change) so the sign always
    // matches the named team: "If Lower Seed Wins" is positive when the lower seed wins.
    const hiSwIfLo  = isAway ? (swL !== null ? +(-swL).toFixed(1) : null) : swT;
    const loSwIfLo  = hiSwIfLo !== null ? +(-hiSwIfLo).toFixed(1) : null;
    const lastHiWin = isAway ? lastT : lastL;
    const lastLoWin = isAway ? lastL : lastT;

    const slCls = hiSwIfHi === null ? 'c-n' : (hiSwIfHi > 0 ? 'c-l' : hiSwIfHi < 0 ? 'c-t' : 'c-n');
    const stCls = loSwIfLo === null ? 'c-n' : 'c-l';

    const badge = sub
      ? `<span class="seed-badge ${{isAway ? 'badge-away' : 'badge-home'}}">${{isAway ? 'LO' : 'HI'}}</span>`
      : '';
    const tr = document.createElement('tr');
    if (isAway) tr.classList.add('away-row');
    tr.innerHTML = `
      <td>${{badge}}${{label}}</td>
      <td class="c-n">${{total}}</td>
      <td style="color:${{pctColor(hiPct)}}">${{fmt(hiPct)}}</td>
      <td style="color:${{pctColor(loPct)}}">${{fmt(loPct)}}</td>
      <td class="${{slCls}}">${{fmtSw(hiSwIfHi)}}</td>
      <td class="${{stCls}}">${{fmtSw(loSwIfLo)}}</td>
      <td>${{lastHiWin || 'N/A'}}</td>
      <td>${{lastLoWin || 'N/A'}}</td>
    `;
    tbody.appendChild(tr);
  }});
}}

// ---- Tab switching ----

function switchTab(name) {{
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('active', p.id === 'tab-' + name));
}}

// ---- Round filter ----

function onRoundChange() {{
  selectedRounds = new Set();
  document.querySelectorAll('.round-cb:checked').forEach(cb => {{
    selectedRounds.add(Number(cb.value));
  }});
  buildTableCombined();
  buildTableSeeded();
}}

function el(id)   {{ return document.getElementById(id); }}
function fmt(v)   {{ return v == null ? 'N/A' : v.toFixed(1) + '%'; }}
function fmtSw(v) {{ return v == null ? 'N/A' : (v >= 0 ? '+' : '') + v.toFixed(1) + '%'; }}
function pctColor(v) {{
  if (v == null) return '#8888b0';
  return `hsl(${{(v * 1.2).toFixed(1)}}, 72%, 52%)`;
}}

buildTableCombined();
buildTableSeeded();
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

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Written: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
