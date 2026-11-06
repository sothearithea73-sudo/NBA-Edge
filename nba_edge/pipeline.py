"""One full update: fetch -> model -> markets -> history -> JSON files for the site."""
import logging
from collections import defaultdict
from datetime import timedelta
from zoneinfo import ZoneInfo

from . import history, markets, situational
from .geo import TEAM_COLORS, TEAM_NAMES
from .model import project_game, team_stats
from .players import compute_impacts, projected_lineup, team_injury_adjustment, team_roster
from .ratings import fit_ratings
from .situational import Schedule
from .sources.espn import ET
from .sources.odds import parse_odds
from .util import ROOT, Paths, load_config, load_json, norm_name, parse_dt, save_json, utcnow

log = logging.getLogger("nba_edge")


def annotate(kind, msg):
    """Print a GitHub Actions annotation (shows up in the run summary) and log it."""
    print(f"::{kind}::{msg}", flush=True)


def pick_slate(games, now):
    today = now.astimezone(ET).date()
    by_date = defaultdict(list)
    for g in games:
        by_date[g["et_date"]].append(g)
    for d in sorted(k for k in by_date if k >= today):
        if any(g["state"] != "post" for g in by_date[d]):
            return d, sorted(by_date[d], key=lambda g: g["tip"])
    return today, []


def fmt_local(dt, tz):
    t = dt.astimezone(tz)
    return t.strftime("%a %-d %b, %-I:%M%p").replace("AM", "am").replace("PM", "pm")


def _get_odds(sources, cfg, paths, state, now, games):
    oc = cfg["odds"]
    cache_path = paths.cache / "odds_latest.json"
    day = now.astimezone(ET).date().isoformat()
    calls = {k: v for k, v in state.get("odds_calls", {}).items() if k >= (now - timedelta(days=7)).date().isoformat()}
    state["odds_calls"] = calls
    raw, fetched_at, meta, msg = None, None, {}, ""
    if calls.get(day, 0) < oc["max_calls_per_day"]:
        try:
            raw, meta = sources.odds()
            fetched_at = now
            calls[day] = calls.get(day, 0) + 1
            save_json(cache_path, {"fetched_at": now.isoformat(), "meta": meta, "events": raw}, indent=None)
            if meta.get("remaining") is not None:
                log.info("Odds API credits remaining this month: %s", meta["remaining"])
        except Exception as e:  # noqa: BLE001 - any failure falls back to the saved odds
            msg = str(e)
            annotate("warning", f"Odds fetch failed: {msg}")
    else:
        msg = f"daily odds-call limit ({oc['max_calls_per_day']}) reached, using last saved odds"
        log.info(msg)
    if raw is None:
        cached = load_json(cache_path)
        if cached:
            raw, fetched_at, meta = cached["events"], parse_dt(cached["fetched_at"]), cached.get("meta", {})
    if raw is None:
        block = f"Odds unavailable ({msg or 'no data'})"
        return {}, {"ok": False, "updated": None, "message": block}, block
    age_h = (now - fetched_at).total_seconds() / 3600
    block = None if age_h <= oc["stale_hours"] else f"Odds are {age_h:.0f}h old, refusing to pick on stale prices"
    status = {"ok": block is None, "updated": fetched_at.isoformat(), "remaining": meta.get("remaining"),
              "message": block or msg or f"{len(raw)} events"}
    return parse_odds(raw, games), status, block


def _market_snapshot(mk_list):
    snap = {}
    for mk in mk_list:
        s0 = mk["sides"][0]
        if mk["market"] == "h2h":
            snap["home_p"] = s0["market_p"]
        elif mk["market"] == "spreads":
            snap["spread"] = s0["line"]
        else:
            snap["total"] = s0["line"]
    return snap


def run(mode="manual", root=ROOT, sources=None, now=None, demo=False):
    paths = Paths(root)
    cfg = load_config(paths.config)
    now = now or utcnow()
    tz = ZoneInfo(cfg["display_timezone"])
    season = cfg["season"]["current"]
    state = load_json(paths.state, {}) or {}
    if sources is None:
        if demo:
            from .sources.demo import DemoSources
            sources = DemoSources(cfg, now)
        else:
            from .sources.live import LiveSources
            sources = LiveSources(cfg, paths, now)

    status, warnings = {}, []
    if demo:
        warnings.append("DEMO DATA: invented teams' players, injuries and odds, for previewing the site only.")

    # 1. Schedule & scores
    try:
        games = sources.games()
        status["schedule"] = {"ok": True, "updated": now.isoformat(), "message": f"{len(games)} games loaded"}
    except Exception as e:  # noqa: BLE001
        annotate("error", f"Schedule/scores fetch failed: {e}")
        status["schedule"] = {"ok": False, "updated": None, "message": str(e)}
        _write_today(paths, now, tz, mode, status, ["Schedule feed is down. No picks today until it recovers."], None, [], cfg)
        return 1
    games_by_id = {g["id"]: g for g in games}
    slate_date, slate = pick_slate(games, now)
    log.info("Slate %s: %d games", slate_date, len(slate))

    # 2. Box scores -> player impact (optional: the model still runs without it)
    try:
        box = sources.box_scores(games)
        status["box_scores"] = {"ok": True, "updated": now.isoformat(), "message": f"{len(box)} games of player data"}
    except Exception as e:  # noqa: BLE001
        box = {}
        annotate("warning", f"Box scores unavailable: {e}")
        status["box_scores"] = {"ok": False, "updated": None, "message": str(e)}
        warnings.append("Player data unavailable: injury adjustments are switched off for this run.")

    ratings = fit_ratings(games, slate_date, cfg, season)
    if ratings.n_games < 20:
        warnings.append("Not enough finished games to rate teams yet.")
    impacts, meta = compute_impacts(box, games_by_id, season, slate_date, cfg)
    stats = team_stats(games, box, season, slate_date, ratings)

    # 3. Injuries (picks are blocked without them)
    name_map = {norm_name(v): k for k, v in TEAM_NAMES.items()}
    for g in games:
        name_map[norm_name(g["home_name"])] = g["home"]
        name_map[norm_name(g["away_name"])] = g["away"]
    injury_block = None
    try:
        injuries = sources.injuries(name_map)
        status["injuries"] = {"ok": True, "updated": now.isoformat(),
                              "message": f"{sum(len(v) for v in injuries.values())} players listed"}
    except Exception as e:  # noqa: BLE001
        injuries = {}
        injury_block = "Injury report unavailable, so no picks until it's back"
        annotate("warning", f"Injury fetch failed: {e}")
        status["injuries"] = {"ok": False, "updated": None, "message": str(e)}

    # 4. Odds
    upcoming = [g for g in slate if g["state"] == "pre"]
    odds_by_game, status["odds"], odds_block = _get_odds(sources, cfg, paths, state, now, games) if upcoming or slate else ({}, {"ok": True, "message": "no games"}, None)

    # 5. Each game
    sched = Schedule(games)
    opens = state.setdefault("odds_open", {})
    games_out = []
    for g in slate:
        H, A = g["home"], g["away"]
        adj_h, inj_h = team_injury_adjustment(H, impacts, injuries, cfg)
        adj_a, inj_a = team_injury_adjustment(A, impacts, injuries, cfg)
        proj = project_game(g, ratings, sched, adj_h, adj_a, cfg, situational)
        og = odds_by_game.get(g["id"])
        mk = markets.evaluate(g, proj, og, cfg)
        gw = []
        block = None
        if g["state"] != "pre":
            block = "Game has started" if g["state"] == "in" else "Game finished"
        elif injury_block:
            block = injury_block
        elif odds_block:
            block = odds_block
        elif og and og.get("last_update") and (now - parse_dt(og["last_update"])).total_seconds() > cfg["odds"]["stale_hours"] * 3600:
            block = "This game's odds haven't updated recently"
        if g["state"] == "pre" and not og and not odds_block:
            gw.append("No bookmaker odds for this game yet.")
        lineups = {t: projected_lineup(t, impacts, meta, injuries, cfg) for t in (H, A)}
        for t, rows in ((H, inj_h), (A, inj_a)):
            for r in rows:
                if r["status"] in ("questionable", "doubtful", "day-to-day") and abs(r["impact"]) >= 1.0:
                    gw.append(f"{r['name']} ({t}) is {r['status']}: worth ~{abs(r['impact']):.1f} pts. Re-check before tip-off.")
            if stats.get(t, {}).get("games", 0) < 5:
                gw.append(f"{t} has played under 5 games this season: ratings lean on last season.")
        markets.decide(mk, cfg, block)
        snap = _market_snapshot(mk)
        if snap and g["id"] not in opens and g["state"] == "pre":
            opens[g["id"]] = dict(snap, at=now.isoformat())
        games_out.append({
            "id": g["id"], "tip_utc": g["tip"].isoformat(), "tip_local": fmt_local(g["tip"], tz),
            "et_date": g["et_date"].isoformat(), "state": g["state"], "status_text": g["status_text"],
            "score": f"{g['away_score']}-{g['home_score']}" if g["state"] != "pre" else None,
            "home": {"abbr": H, "name": TEAM_NAMES.get(H, g["home_name"]), "colors": TEAM_COLORS.get(H, ("#444", "#888")), "stats": stats.get(H, {}),
                     "injuries": inj_h, "lineup": lineups[H], "roster": team_roster(H, impacts, injuries, cfg), "injury_adj": round(adj_h, 2)},
            "away": {"abbr": A, "name": TEAM_NAMES.get(A, g["away_name"]), "colors": TEAM_COLORS.get(A, ("#444", "#888")), "stats": stats.get(A, {}),
                     "injuries": inj_a, "lineup": lineups[A], "roster": team_roster(A, impacts, injuries, cfg), "injury_adj": round(adj_a, 2)},
            "projection": proj, "markets": mk, "warnings": gw,
            "movement": {"open": opens.get(g["id"]), "now": snap},
            "odds_updated": (og or {}).get("last_update"),
        })
    scale = markets.cap_exposure(games_out, cfg)
    if scale < 1:
        warnings.append(f"Stakes scaled to {scale:.0%} to stay under the daily exposure limit.")

    # keep state small: forget openers for games more than a week old
    keep = {g["id"] for g in games if g["et_date"] >= slate_date - timedelta(days=7)}
    state["odds_open"] = {k: v for k, v in opens.items() if k in keep}

    # 6. History, results, files
    hist = load_json(paths.history, {"picks": {}}) or {"picks": {}}
    history.update(hist, games_out, games_by_id, now, cfg)
    if not demo:
        save_json(paths.history, hist)
    if mode == "pretip":
        lo, hi = cfg["schedule"]["pretip_window_minutes"]
        done = state.setdefault("pretip_done", [])
        for g in upcoming:
            mins = (g["tip"] - now).total_seconds() / 60
            if lo - 30 <= mins <= hi and g["tip"].isoformat() not in done:
                done.append(g["tip"].isoformat())
        state["pretip_done"] = done[-60:]
    state["last_run"] = {"at": now.isoformat(), "mode": mode}
    if not demo:
        save_json(paths.state, state)
    _write_today(paths, now, tz, mode, status, warnings, slate_date, games_out, cfg)
    res = history.summary(hist)
    res["generated_at"] = now.isoformat()
    res["backtest"] = load_json(paths.backtest)
    save_json(paths.site_data / "results.json", res)
    log.info("Done: %d games, %d value bets", len(games_out),
             sum(mk["pick"]["verdict"] == "Value bet" for g in games_out for mk in g["markets"]))
    return 0


def _write_today(paths, now, tz, mode, status, warnings, slate_date, games_out, cfg):
    b = cfg["betting"]
    save_json(paths.site_data / "today.json", {
        "generated_at": now.isoformat(), "generated_local": fmt_local(now, tz), "mode": mode,
        "timezone": cfg["display_timezone"], "slate_date": slate_date.isoformat() if slate_date else None,
        "sources": status, "warnings": warnings, "games": games_out,
        "settings": {"edge_threshold": b["edge_threshold"], "kelly_fraction": b["kelly_fraction"],
                     "max_stake_pct": b["max_stake_pct"], "max_daily_exposure_pct": b["max_daily_exposure_pct"],
                     "model_weight": cfg["model"]["model_weight"]},
    })
