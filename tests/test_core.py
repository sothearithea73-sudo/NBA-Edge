"""Run with:  python -m pytest -q"""
import shutil
from datetime import date, datetime, timedelta, timezone

import pytest

from nba_edge import gate, history, markets
from nba_edge.geo import km_between
from nba_edge.pipeline import run
from nba_edge.players import compute_impacts, team_injury_adjustment
from nba_edge.ratings import fit_ratings
from nba_edge.sources.demo import DemoSources
from nba_edge.sources.espn import normalize_status, parse_event
from nba_edge.sources.odds import parse_odds
from nba_edge.util import ROOT, load_config, load_json

CFG = load_config()
NOW = datetime(2026, 11, 6, 8, 0, tzinfo=timezone.utc)


def test_no_vig_sums_to_one():
    a, b = markets.no_vig(1.91, 1.91)
    assert a == pytest.approx(0.5) and a + b == pytest.approx(1)
    a, b = markets.no_vig(1.5, 2.6)
    assert a + b == pytest.approx(1) and a > b


def test_kelly():
    assert markets.kelly(0.55, 2.0) == pytest.approx(0.10)
    assert markets.kelly(0.45, 2.0) == 0.0


def test_fair_at_line_identity_and_direction():
    assert markets.fair_at_line("spreads", "home", -4.5, 0.5, -4.5, 12.5) == 0.5
    # getting +1 point more than the close is worth more than 50%
    assert markets.fair_at_line("spreads", "home", -4.5, 0.5, -3.5, 12.5) > 0.5
    assert markets.fair_at_line("totals", "over", 220.5, 0.5, 219.5, 18) > 0.5
    assert markets.fair_at_line("totals", "under", 220.5, 0.5, 219.5, 18) < 0.5


def test_verdicts_and_one_bet_per_game():
    side = lambda name, edge, ev: {"side": name, "label": name, "line": None, "edge": edge, "ev": ev, "best_price": 2.0,
                                   "best_book": "X", "kelly": 0.1, "n_books": 4}
    mk = [{"market": "h2h", "sides": [side("home", 0.05, 0.08), side("away", -0.05, -0.1)]},
          {"market": "spreads", "sides": [side("home", 0.04, 0.05), side("away", -0.04, -0.09)]},
          {"market": "totals", "sides": [side("over", 0.01, 0.0), side("under", -0.01, -0.05)]}]
    markets.decide(mk, CFG)
    assert mk[0]["pick"]["verdict"] == "Value bet" and mk[0]["pick"]["stake_pct"] == pytest.approx(0.02)
    assert mk[1]["pick"]["verdict"] == "Lean"  # downgraded: correlated with the moneyline
    assert mk[2]["pick"]["verdict"] == "Pass"
    markets.decide(mk, CFG, block_reason="Injury report unavailable")
    assert all(m["pick"]["verdict"] == "No pick" and m["pick"]["stake_pct"] == 0 for m in mk)


def test_ratings_recover_strengths():
    src = DemoSources(CFG, NOW)
    games = src.games()
    r = fit_ratings(games, NOW.date(), CFG, CFG["season"]["current"])
    true_net = {t: o + d for t, (o, d) in src.true.items()}
    est = {t: r.net(t) for t in true_net}
    best_true = sorted(true_net, key=true_net.get)[-5:]
    worst_true = sorted(true_net, key=true_net.get)[:5]
    assert min(est[t] for t in best_true) > max(est[t] for t in worst_true)
    assert 0.5 < r.hca < 4.5


def test_injury_logic_priced_in_vs_new():
    imp = {"BOS": {
        "1": {"name": "Star", "value": 5.0, "played_share": 1.0, "recent": True, "exp_min": 34},
        "2": {"name": "Long Out", "value": 3.0, "played_share": 0.0, "recent": False, "exp_min": 20},
        "3": {"name": "Healthy", "value": 2.0, "played_share": 1.0, "recent": True, "exp_min": 30}}}
    inj = {"BOS": [{"id": "1", "name": "Star", "status": "out", "detail": ""},
                   {"id": "2", "name": "Long Out", "status": "out", "detail": ""}]}
    adj, rows = team_injury_adjustment("BOS", imp, inj, CFG)
    assert adj == pytest.approx(-5.0)  # star ruled out today; long absence already priced in
    assert {r["name"]: r["impact"] for r in rows} == {"Star": -5.0, "Long Out": 0.0}


def test_onoff_from_box():
    src = DemoSources(CFG, NOW)
    games = src.games()
    box = src.box_scores(games)
    imp, meta = compute_impacts(box, {g["id"]: g for g in games}, CFG["season"]["current"], NOW.date(), CFG)
    assert len(imp) == 30 and all(len(v) >= 8 for v in imp.values())
    assert all(len(m["last_starters"]) == 5 for m in meta.values())


def test_grading():
    g = {"home": "BOS", "away": "NY", "home_score": 110, "away_score": 105, "completed": True}
    p = {"market": "spreads", "side": "home", "line": -5.0, "price": 1.9, "stake_pct": 0.01, "close_line": -5.0, "close_fair_p": 0.5}
    history.grade(p, g, CFG)
    assert p["result"] == "push" and p["profit_units"] == 0
    p = {"market": "totals", "side": "over", "line": 210.5, "price": 2.0, "stake_pct": 0.02, "close_line": 211.5, "close_fair_p": 0.5}
    history.grade(p, g, CFG)
    assert p["result"] == "win" and p["profit_units"] == pytest.approx(2.0) and p["clv"] > 0
    p = {"market": "h2h", "side": "away", "line": None, "price": 2.5, "stake_pct": 0.01, "close_line": None, "close_fair_p": 0.45}
    history.grade(p, g, CFG)
    assert p["result"] == "loss" and p["profit_units"] == -1.0 and p["clv"] == pytest.approx(0.125)


def test_espn_parsers():
    ev = {"id": "401", "date": "2026-11-07T00:00Z", "season": {"year": 2027, "type": 2},
          "competitions": [{"neutralSite": False, "status": {"type": {"state": "pre", "completed": False, "shortDetail": "7:00 PM ET"}},
                            "competitors": [{"homeAway": "home", "score": "0", "team": {"abbreviation": "GSW", "displayName": "Golden State Warriors"}},
                                            {"homeAway": "away", "score": "0", "team": {"abbreviation": "LAC", "displayName": "LA Clippers"}}]}]}
    g = parse_event(ev)
    assert g["home"] == "GS" and g["et_date"] == date(2026, 11, 6) and g["season"] == 2027
    ev["season"]["type"] = 1
    assert parse_event(ev) is None  # preseason skipped
    assert normalize_status("Day-To-Day GTD") == "questionable"
    assert normalize_status("Out") == "out"
    assert normalize_status("Doubtful") == "doubtful"


def test_odds_matching_handles_la_clippers():
    tip = datetime(2026, 11, 7, 3, 0, tzinfo=timezone.utc)
    games = [{"id": "1", "home": "LAL", "away": "LAC", "home_name": "Los Angeles Lakers", "away_name": "LA Clippers", "tip": tip}]
    ev = [{"commence_time": "2026-11-07T03:10:00Z", "home_team": "Los Angeles Lakers", "away_team": "Los Angeles Clippers",
           "bookmakers": [{"title": "TAB", "last_update": "2026-11-06T20:00:00Z", "markets": [
               {"key": "h2h", "outcomes": [{"name": "Los Angeles Lakers", "price": 1.8}, {"name": "Los Angeles Clippers", "price": 2.05}]}]}]}]
    out = parse_odds(ev, games)
    assert out["1"]["h2h"][0] == {"book": "TAB", "home": 1.8, "away": 2.05}


def test_gate():
    tip = NOW + timedelta(minutes=60)
    games = [{"id": "1", "tip": tip, "et_date": date(2026, 11, 6), "state": "pre"}]
    assert gate.decide("workflow_dispatch", "", NOW, games, {}, CFG)[0]
    assert gate.decide("schedule", CFG["schedule"]["morning_cron"], NOW, games, {}, CFG)[1] == "morning"
    assert gate.decide("schedule", "15,45 15-23 * * *", NOW, games, {}, CFG)[1] == "pretip"
    assert not gate.decide("schedule", "15,45 15-23 * * *", NOW, games, {"pretip_done": [tip.isoformat()]}, CFG)[0]
    assert not gate.decide("schedule", "15,45 15-23 * * *", NOW - timedelta(hours=3), games, {}, CFG)[0]


def test_full_demo_pipeline(tmp_path):
    shutil.copy(ROOT / "config.yaml", tmp_path / "config.yaml")
    assert run(mode="manual", root=tmp_path, demo=True, now=NOW) == 0
    today = load_json(tmp_path / "site/data/today.json")
    assert today["games"], "demo slate should have games"
    for g in today["games"]:
        assert 0 < g["projection"]["home_win_p"] < 1
        assert {m["market"] for m in g["markets"]} == {"h2h", "spreads", "totals"}
    total = sum(m["pick"]["stake_pct"] for g in today["games"] for m in g["markets"])
    assert total <= CFG["betting"]["max_daily_exposure_pct"] + 1e-9
    assert load_json(tmp_path / "site/data/results.json")["overall"]["bets"] == 0
