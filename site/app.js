/* NBA Edge front end: reads data/today.json + data/results.json and renders them. */
(function () {
  "use strict";

  const $ = (s, el = document) => el.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pct = (p, d = 1) => (p == null ? "–" : (p * 100).toFixed(d) + "%");
  const signed = (x, d = 1) => (x == null ? "–" : (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(d));
  const money = (x) => "$" + (x >= 100 ? Math.round(x).toLocaleString() : x.toFixed(2));
  const cls = (x) => (x > 0 ? "pos" : x < 0 ? "neg" : "");

  // localStorage can be missing or blocked (private mode, embedded previews): never let it break the page
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* ignore */ } },
  };

  let TODAY = null, RESULTS = null;
  let bankroll = Number(store.get("bankroll", 1000)) || 0;

  async function load(name, preset) {
    if (preset) return preset;
    const r = await fetch(`data/${name}.json?t=${Date.now()}`, { cache: "no-store" });
    if (!r.ok) throw new Error(`${name}.json: HTTP ${r.status}`);
    return r.json();
  }

  function ago(iso) {
    if (!iso) return "never";
    const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
    if (m < 1) return "just now";
    if (m < 60) return `${m} min ago`;
    if (m < 48 * 60) return `${Math.round(m / 60)} h ago`;
    return `${Math.round(m / 1440)} days ago`;
  }

  const SOURCE_NAMES = { schedule: "Schedule & scores", box_scores: "Player data", injuries: "Injury report", odds: "Odds" };

  // ---------- Today ----------
  function renderToday() {
    const el = $("#view-today");
    const d = TODAY;
    if (!d) { el.innerHTML = `<div class="empty">No data yet. Run the GitHub Action once (see README).</div>`; return; }
    const games = d.games || [];
    let html = `<div class="meta">Slate for US date ${esc(d.slate_date || "–")} · updated ${esc(d.generated_local)} (${ago(d.generated_at)}) · times in ${esc(d.timezone)}</div>`;
    html += `<div class="sources">` + Object.entries(d.sources || {}).map(([k, s]) =>
      `<span class="src ${s.ok ? "" : "bad"}" title="${esc(s.message)}">${s.ok ? "✓" : "!"} ${esc(SOURCE_NAMES[k] || k)} · ${ago(s.updated)}</span>`).join("") + `</div>`;
    (d.warnings || []).forEach((w) => { html += `<div class="banner">${esc(w)}</div>`; });

    const values = [];
    games.forEach((g) => g.markets.forEach((m) => { if (m.pick.verdict === "Value bet") values.push({ g, m }); }));
    const total = values.reduce((s, x) => s + x.m.pick.stake_pct, 0);
    $("#exposure").textContent = values.length
      ? `Today: ${values.length} value bet(s), total ${pct(total)} of bankroll = ${money(total * bankroll)} (limit ${pct(d.settings.max_daily_exposure_pct, 0)})`
      : "Today: no value bets";

    html += `<div class="summary"><h2>Today's summary</h2>`;
    if (!games.length) html += `<p class="muted">No games scheduled.</p>`;
    else if (!values.length) html += `<p>No bets clear the ${pct(d.settings.edge_threshold, 0)} edge bar today. Passing is a valid outcome: it's how you avoid paying the bookmaker's margin.</p>`;
    else html += `<ul>` + values.map(({ g, m }) => `<li><strong>${esc(m.pick.label)}</strong> @ ${m.pick.price.toFixed(2)} (${esc(m.pick.book)}) · ${esc(g.away.abbr)} @ ${esc(g.home.abbr)} · edge ${pct(m.pick.edge)} · stake <span class="stake">${money(m.pick.stake_pct * bankroll)}</span></li>`).join("") + `</ul>`;
    html += `</div>`;

    html += games.map(renderGame).join("");
    el.innerHTML = html;
  }

  function teamLine(t) {
    const s = t.stats || {};
    return `${esc(s.record || "0-0")} · last 10 ${esc(s.last10 || "–")} (${signed(s.last10_margin)})`;
  }

  function renderGame(g) {
    const p = g.projection;
    const H = g.home.abbr, A = g.away.abbr;
    const hp = p.home_win_p, ap = 1 - hp;
    const fav = p.margin >= 0 ? H : A;
    const lo = p.margin_lo, hi = p.margin_hi;
    const [hc, hc2] = g.home.colors || ["#444", "#888"];
    const [ac, ac2] = g.away.colors || ["#444", "#888"];
    const badge = (t, c, c2) => `<span class="badge" style="--c:${esc(c)};--c2:${esc(c2)}">${esc(t.abbr)}</span>`;
    const hasValue = g.markets.some((m) => m.pick.verdict === "Value bet");
    let h = `<article class="game${hasValue ? " has-value" : ""}" id="g${esc(g.id)}" style="--hc:${esc(hc)};--ac:${esc(ac)}">
      <div class="stripe"></div>
      <div class="when">${g.state === "pre" ? esc(g.tip_local) : esc(g.status_text) + (g.score ? " · " + esc(g.score) : "")}${hasValue ? '<span class="vflag">Value</span>' : ""}</div>
      <div class="teams">
        <div class="side">${badge(g.away, ac, ac2)}<div><div class="tname">${esc(g.away.name)}</div><div class="record">${teamLine(g.away)}</div></div><div class="big">${pct(ap, 0)}</div></div>
        <div class="side">${badge(g.home, hc, hc2)}<div><div class="tname">${esc(g.home.name)} <span class="homechip">home</span></div><div class="record">${teamLine(g.home)}</div></div><div class="big">${pct(hp, 0)}</div></div>
      </div>
      <div class="bar" title="Model win probability"><div class="a" style="flex:${ap}"></div><div class="h" style="flex:${hp}"></div></div>
`;
    h += `<div class="proj">Model: <strong>${esc(fav)} by ${Math.abs(p.margin).toFixed(1)}</strong> · total <strong>${p.total.toFixed(1)}</strong>
      <div class="range">${Math.round(p.interval * 100)}% range: ${esc(H)} ${signed(lo, 0)} to ${signed(hi, 0)} margin · total ${p.total_lo.toFixed(0)}–${p.total_hi.toFixed(0)}</div></div>`;

    if (!g.markets.length) h += `<div class="pick"><span class="mk">Odds</span><span class="why">No bookmaker prices yet.</span></div>`;
    h += `<div class="picks">` + g.markets.map((m) => {
      const k = m.pick.verdict === "Value bet" ? "value" : m.pick.verdict === "Lean" ? "lean" : "";
      let txt = `<span class="v">${esc(m.pick.verdict)}</span>`;
      if (m.pick.verdict === "Value bet" || m.pick.verdict === "Lean") {
        txt += ` · ${esc(m.pick.label)} @ ${m.pick.price.toFixed(2)} (${esc(m.pick.book)})<div class="why">edge ${pct(m.pick.edge)} · EV ${signed(m.pick.ev * 100)}% per $1`;
        if (m.pick.stake_pct > 0) txt += ` · stake <span class="stake">${money(m.pick.stake_pct * bankroll)}</span> (${pct(m.pick.stake_pct)})`;
        if (m.pick.reason) txt += ` · ${esc(m.pick.reason)}`;
        txt += `</div>`;
      } else if (m.pick.reason) txt += `<div class="why">${esc(m.pick.reason)}</div>`;
      else txt += `<div class="why">best side ${esc(m.pick.label)}: edge ${pct(m.pick.edge)}, under the bar</div>`;
      return `<div class="pick ${k}"><span class="mk">${esc(m.title)}</span><span>${txt}</span></div>`;
    }).join("") + `</div>`;

    if (g.warnings.length) h += `<ul class="warns">` + g.warnings.map((w) => `<li>${esc(w)}</li>`).join("") + `</ul>`;

    if (g.markets.length) {
      h += `<details><summary>Model vs market</summary><div class="tw"><table><tr><th>Bet</th><th class="num">Model</th><th class="num">Market</th><th class="num">Edge</th><th class="num">Price</th><th class="num">EV</th></tr>`;
      g.markets.forEach((m) => m.sides.forEach((s) => {
        h += `<tr><td>${esc(s.label)}<div class="small">${s.n_books} books · ${esc(s.best_book)}</div></td><td class="num">${pct(s.model_p)}</td><td class="num">${pct(s.market_p)}</td>
          <td class="num ${cls(s.edge)}">${signed(s.edge * 100)}%</td><td class="num">${s.best_price.toFixed(2)}</td><td class="num ${cls(s.ev)}">${signed(s.ev * 100)}%</td></tr>`;
      }));
      const mv = g.movement || {};
      let mvt = "";
      if (mv.open && mv.now) {
        if (mv.open.spread != null && mv.now.spread != null) mvt += `Spread ${esc(H)} opened ${signed(mv.open.spread)}, now ${signed(mv.now.spread)}. `;
        if (mv.open.total != null && mv.now.total != null) mvt += `Total opened ${mv.open.total}, now ${mv.now.total}. `;
        if (mv.open.home_p != null && mv.now.home_p != null) mvt += `${esc(H)} win chance (market) ${pct(mv.open.home_p)} → ${pct(mv.now.home_p)}.`;
      }
      h += `</table></div><p class="small">Model = the model on its own. Market = bookmaker consensus with the margin removed. Edge and EV use a ${Math.round(TODAY.settings.model_weight * 100)}/${100 - Math.round(TODAY.settings.model_weight * 100)} blend of model and market, to curb overconfidence. Price = best available.
        ${mvt ? "<br>Line movement: " + mvt : ""} ${g.odds_updated ? "<br>Odds updated " + ago(g.odds_updated) + "." : ""}</p></details>`;
    }

    h += `<details><summary>Injuries & lineups</summary><div class="cols">` + [g.away, g.home].map((t) => {
      let c = `<div><h4>${esc(t.name)} <span class="small">(${signed(t.injury_adj)} pts)</span></h4>`;
      c += t.injuries.length ? `<table>` + t.injuries.map((i) => `<tr><td>${esc(i.name)}<span class="tag ${esc(i.status)}">${esc(i.status)}</span>
          <div class="small">${esc(i.detail)}${i.note ? " · " + esc(i.note) : ""}</div></td><td class="num ${cls(i.impact)}">${signed(i.impact)}</td></tr>`).join("") + `</table>` : `<div class="small">No one listed.</div>`;
      c += `<div class="small" style="margin-top:6px"><strong>Projected starters:</strong> ` + (t.lineup.length ? t.lineup.map((x) => esc(x.name) + (x.note ? ` <em>(${esc(x.note)})</em>` : "")).join(", ") : "not available yet") + `</div></div>`;
      return c;
    }).join("") + `</div><p class="small">Starters are projected from the last game, adjusted for the injury report. Confirmed lineups come out ~30 min before tip.</p></details>`;

    const jersey = (p, c, c2) => {
      const parts = String(p.name || "").trim().split(/\s+/);
      const last = (parts.length > 1 ? parts.slice(1).join(" ") : parts[0] || "").toUpperCase();
      const num = p.jersey !== undefined && p.jersey !== "" ? p.jersey : initials(p.name);
      const fit = last.length > 7 ? ` textLength="40" lengthAdjust="spacingAndGlyphs"` : "";
      return `<svg class="jersey" viewBox="0 0 60 64" role="img" aria-label="${esc(last)} ${esc(num)}">
        <path d="M15 2h8q7 9 14 0h8v8q4 8 12 10v42H3V20q8-2 12-10z" fill="${esc(c)}" stroke="${esc(c2)}" stroke-width="2.5" stroke-linejoin="round"/>
        <text x="30" y="27" text-anchor="middle" class="jn"${fit}>${esc(last)}</text>
        <text x="30" y="53" text-anchor="middle" class="jnum" stroke="${esc(c2)}">${esc(num)}</text></svg>`;
    };
    const initials = (n) => String(n || "?").split(/\s+/).filter(Boolean).map((w) => w[0]).slice(0, 2).join("").toUpperCase();
    h += `<details><summary>Rosters</summary><div class="cols">` + [[g.away, ac, ac2], [g.home, hc, hc2]].map(([t, c, c2]) => {
      const r = t.roster || [];
      if (!r.length) return `<div><h4>${esc(t.name)}</h4><div class="small">No player data yet.</div></div>`;
      return `<div><h4>${esc(t.name)}</h4><ul class="roster">` + r.map((p) => `<li class="${p.status !== "available" ? "inj" : ""}">
          ${jersey(p, c, c2)}
          <span class="pn">${esc(p.name)}${p.status !== "available" ? `<span class="tag ${esc(p.status)}">${esc(p.status)}</span>` : ""}
            <span class="small">${p.mpg.toFixed(0)} min · played ${Math.round(p.played_share * 100)}% lately</span></span>
          <span class="num ${cls(p.impact)}" title="On/off impact in points per game">${signed(p.impact)}</span></li>`).join("") + `</ul></div>`;
    }).join("") + `</div><p class="small">Right-hand number = on/off impact: roughly how many points of margin the team gains with this player playing his usual minutes (shrunk for small samples).</p></details>`;
    h += `<details><summary>Key factors</summary><table><tr><td>Team ratings (${esc(H)} home)</td><td class="num">${signed(p.base_margin)}</td></tr>`;
    h += `<tr><td class="small" colspan="2">Includes home court worth ${p.home_court.toFixed(1)} pts</td></tr>`;
    p.adjustments.forEach((a) => { h += `<tr><td>${esc(a.label)}</td><td class="num">${signed(a.size)} ${esc(a.favours)}</td></tr>`; });
    h += `<tr><th>Projected margin (${esc(H)})</th><th class="num">${signed(p.margin)}</th></tr></table><div class="cols">` + [g.away, g.home].map((t) => {
      const s = t.stats || {};
      return `<div class="small"><strong>${esc(t.abbr)}</strong>: adjusted net ${signed(s.adj_net)} (off ${signed(s.adj_off)}, def ${signed(s.adj_def)}) · ORtg ${s.ortg ?? "–"} · DRtg ${s.drtg ?? "–"} · pace ${s.pace ?? "–"}</div>`;
    }).join("") + `</div></details></article>`;
    return h;
  }

  // ---------- Results ----------
  function tile(k, n) { return `<div class="tile"><div class="k">${k}</div><div class="n">${n}</div></div>`; }

  function renderResults() {
    const el = $("#view-results");
    const r = RESULTS;
    if (!r) { el.innerHTML = `<div class="empty">No results yet.</div>`; return; }
    const o = r.overall;
    let h = `<div class="meta">Every Value bet the site has flagged, graded after the game. 1 unit = 1% of bankroll.</div><div class="tiles">`;
    h += tile("Graded bets", o.bets) + tile("Record (W-L-P)", `${o.wins}-${o.losses}-${o.pushes}`) + tile("Profit (units)", signed(o.profit_units, 2))
      + tile("ROI (as staked)", o.roi == null ? "–" : signed(o.roi * 100) + "%") + tile("ROI (flat 1u)", o.flat_roi == null ? "–" : signed(o.flat_roi * 100) + "%")
      + tile("Avg CLV", o.avg_clv == null ? "–" : signed(o.avg_clv * 100) + "%") + tile("Beat closing line", o.beat_close_pct == null ? "–" : pct(o.beat_close_pct, 0)) + `</div>`;
    h += `<div class="panel small">Read this honestly: under ~300 bets, profit is mostly luck. <strong>Closing line value (CLV)</strong> settles faster. If your bets keep getting better prices than the final market, the model may have an edge. If CLV is negative, the market knew more than the model.</div>`;
    const bm = r.by_market || {};
    if (Object.keys(bm).length) {
      h += `<div class="panel"><h3>By market</h3><table><tr><th>Market</th><th class="num">Bets</th><th class="num">W-L-P</th><th class="num">Units</th><th class="num">ROI</th><th class="num">CLV</th></tr>`;
      const names = { h2h: "Moneyline", spreads: "Spread", totals: "Total" };
      Object.entries(bm).forEach(([k, s]) => { h += `<tr><td>${names[k] || k}</td><td class="num">${s.bets}</td><td class="num">${s.wins}-${s.losses}-${s.pushes}</td><td class="num ${cls(s.profit_units)}">${signed(s.profit_units, 2)}</td><td class="num">${s.roi == null ? "–" : signed(s.roi * 100) + "%"}</td><td class="num">${s.avg_clv == null ? "–" : signed(s.avg_clv * 100) + "%"}</td></tr>`; });
      h += `</table></div>`;
    }
    const picks = r.picks || [];
    h += `<div class="panel"><h3>Pick log</h3>`;
    h += picks.length ? `<table><tr><th>Date</th><th>Bet</th><th class="num">Price</th><th class="num">Stake</th><th>Result</th><th class="num">Units</th><th class="num">CLV</th></tr>` + picks.slice(0, 200).map((p) =>
      `<tr><td>${esc(p.date)}<div class="small">${esc(p.matchup)}</div></td><td>${esc(p.label)}<div class="small">${esc(p.book)}</div></td><td class="num">${p.price.toFixed(2)}</td><td class="num">${(p.stake_pct * 100).toFixed(2)}u</td>
       <td>${p.result ? esc(p.result) + `<div class="small">${esc(p.final || "")}</div>` : "pending"}</td><td class="num ${cls(p.profit_units)}">${p.profit_units == null ? "–" : signed(p.profit_units, 2)}</td><td class="num ${cls(p.clv)}">${p.clv == null ? "–" : signed(p.clv * 100) + "%"}</td></tr>`).join("") + `</table>`
      : `<p class="small">No value bets logged yet.</p>`;
    h += `</div>`;
    const b = r.backtest;
    h += `<div class="panel"><h3>Backtest</h3>`;
    if (!b) h += `<p class="small">Not run yet. See the README: <code>python -m nba_edge.backtest</code>.</p>`;
    else {
      h += `<p class="small">${b.games} past games (seasons ${b.seasons.join(", ")}), predicted using only earlier games. ${esc(b.notes)}</p><table>
        <tr><td>Log loss (lower is better)</td><td class="num">${b.log_loss} <span class="small">vs ${b.log_loss_baseline} baseline</span></td></tr>
        <tr><td>Brier score</td><td class="num">${b.brier}</td></tr><tr><td>Picked the winner</td><td class="num">${pct(b.accuracy)}</td></tr>
        <tr><td>Margin error (RMSE)</td><td class="num">${b.margin_rmse} pts</td></tr><tr><td>Total error (RMSE)</td><td class="num">${b.total_rmse} pts</td></tr></table>`;
      if (b.betting) h += `<p class="small">Against your odds file: ${b.betting.bets} bets, flat ROI ${b.betting.roi_flat == null ? "–" : signed(b.betting.roi_flat * 100) + "%"}. Model log loss ${b.betting.model_log_loss_on_these} vs market ${b.betting.market_log_loss_on_these} (if the market's is lower, the market predicts better).</p>`;
      else h += `<p class="small">ROI against closing lines not tested yet (needs a historical odds file).</p>`;
      if (b.calibration?.length) h += `<table><tr><th>Predicted home win</th><th class="num">Games</th><th class="num">Predicted</th><th class="num">Actual</th></tr>` + b.calibration.map((c) => `<tr><td>${c.bin}</td><td class="num">${c.n}</td><td class="num">${pct(c.predicted)}</td><td class="num">${pct(c.actual)}</td></tr>`).join("") + `</table>`;
    }
    h += `</div>`;
    el.innerHTML = h;
  }

  function renderAbout() {
    const s = TODAY?.settings || {};
    $("#view-about").innerHTML = `<div class="panel prose"><h3>How it works</h3>
      <p><strong>1. Team ratings.</strong> Every finished game this season (and a fading share of last season) feeds an opponent-adjusted rating for each team's offence and defence, with recent games counting more.</p>
      <p><strong>2. Adjustments.</strong> Back-to-backs, 3 games in 4 nights, rest difference, travel and time zones on short rest, altitude in Denver and Utah, and neutral sites.</p>
      <p><strong>3. Injuries.</strong> Each player's on/off impact comes from this season's plus-minus, shrunk for small samples. A team only moves when today's availability differs from how often the player has played lately, so a long-term absence is already priced in.</p>
      <p><strong>4. Probabilities.</strong> The projected margin and total become probabilities using a bell curve fitted by the backtest.</p>
      <p><strong>5. Versus the market.</strong> Bookmaker prices are turned into probabilities with the margin removed. The model is blended ${Math.round((s.model_weight ?? 0.6) * 100)}% with the market to curb overconfidence, then compared. A <em>Value bet</em> needs an edge of at least ${pct(s.edge_threshold ?? 0.03, 0)} and positive expected value. Stakes use ${s.kelly_fraction ?? 0.25}× Kelly, capped at ${pct(s.max_stake_pct ?? 0.02, 0)} per bet and ${pct(s.max_daily_exposure_pct ?? 0.08, 0)} per day.</p>
      <p><strong>What it can't see:</strong> late scratches after the last update, minutes limits, motivation and tanking, locker-room news, and anything the market knows that public data doesn't. Bookmakers' lines are sharp, so expect most days to show few or no value bets.</p>
      <p class="small">Every weight is in <code>config.yaml</code>.</p></div>`;
  }

  // ---------- wiring ----------
  function show(view) {
    document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
    document.querySelectorAll(".view").forEach((v) => { v.hidden = v.id !== `view-${view}`; });
    try { history.replaceState(null, "", "#" + view); } catch (e) { /* ignore */ }
  }

  document.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => show(b.dataset.view)));
  const input = $("#bankroll");
  input.value = bankroll;
  input.addEventListener("input", () => { bankroll = Math.max(0, Number(input.value) || 0); store.set("bankroll", bankroll); renderToday(); });

  (async function init() {
    try { TODAY = await load("today", window.__TODAY__); } catch (e) { TODAY = null; console.error(e); }
    try { RESULTS = await load("results", window.__RESULTS__); } catch (e) { RESULTS = null; console.error(e); }
    renderToday(); renderResults(); renderAbout();
    const v = (location.hash || "#today").slice(1);
    show(["today", "results", "about"].includes(v) ? v : "today");
  })();
})();
