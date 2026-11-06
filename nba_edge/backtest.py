"""Walk-forward backtest: for every past game day, rate teams using only
earlier games, predict that day, then score the predictions.

  python -m nba_edge.backtest --seasons 2025 2026
  python -m nba_edge.backtest --seasons 2026 --odds-csv my_closing_odds.csv
  python -m nba_edge.backtest --demo

What it tests: team ratings + home court + rest/travel/altitude.
What it does NOT test: the injury layer (that needs historical injury reports,
which aren't freely available). Treat live injury adjustments as untested
until the Results page has a few hundred graded bets.

Odds CSV (decimal prices, closing lines), one row per game:
  date,home,away,home_ml,away_ml,home_spread,home_spread_price,away_spread_price,total,over_price,under_price
  2026-01-15,BOS,NY,1.62,2.40,-4.5,1.91,1.91,224.5,1.91,1.91
Only date/home/away/home_ml/away_ml are required. Teams can be abbreviations or full names.
"""
import argparse
import csv
import logging
import math
import sys
from datetime import date
from statistics import mean, pstdev

from . import situational
from .geo import TEAM_NAMES, canon_abbr
from .markets import no_vig
from .model import project_game
from .ratings import fit_ratings
from .situational import Schedule
from .util import NORMAL, Paths, load_config, norm_name, save_json, season_of, utcnow

log = logging.getLogger("nba_edge.backtest")


def _team(x):
    a = canon_abbr(x)
    if a in TEAM_NAMES:
        return a
    return {norm_name(v): k for k, v in TEAM_NAMES.items()}.get(norm_name(x))


def load_odds_csv(path):
    rows = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                key = (date.fromisoformat(r["date"].strip()[:10]), _team(r["home"]), _team(r["away"]))
                rows[key] = {k: float(v) for k, v in r.items() if k not in ("date", "home", "away") and v not in (None, "")}
            except (KeyError, ValueError):
                continue
    return rows


def run_backtest(cfg, games, eval_seasons, odds_rows=None, warmup_games=150):
    sched = Schedule(games)
    sd, sdt = cfg["model"]["margin_sd"], cfg["model"]["total_sd"]
    w = cfg["model"]["model_weight"]
    th = cfg["betting"]["edge_threshold"]
    by_date = {}
    for g in games:
        if g["completed"] and g["season"] in eval_seasons:
            by_date.setdefault(g["et_date"], []).append(g)
    preds = []
    for d in sorted(by_date):
        r = fit_ratings(games, d, cfg, season_of(d))
        if r.n_games < warmup_games:
            continue
        for g in by_date[d]:
            preds.append((g, project_game(g, r, sched, 0.0, 0.0, cfg, situational)))
    if not preds:
        raise SystemExit("Backtest: not enough games to evaluate.")

    ys = [1 if g["home_score"] > g["away_score"] else 0 for g, _ in preds]
    ps = [min(max(p["home_win_p"], 1e-4), 1 - 1e-4) for _, p in preds]
    resid = [(g["home_score"] - g["away_score"]) - p["margin"] for g, p in preds]
    tresid = [(g["home_score"] + g["away_score"]) - p["total"] for g, p in preds]
    base = mean(ys)
    report = {
        "generated_at": utcnow().isoformat(), "seasons": list(eval_seasons), "games": len(preds),
        "log_loss": round(-mean(y * math.log(p) + (1 - y) * math.log(1 - p) for y, p in zip(ys, ps)), 4),
        "log_loss_baseline": round(-mean(y * math.log(base) + (1 - y) * math.log(1 - base) for y in ys), 4),
        "brier": round(mean((p - y) ** 2 for y, p in zip(ys, ps)), 4),
        "accuracy": round(mean((p > 0.5) == (y == 1) for y, p in zip(ys, ps)), 4),
        "margin_rmse": round(math.sqrt(mean(x * x for x in resid)), 2),
        "fitted_margin_sd": round(pstdev(resid), 2), "margin_bias": round(mean(resid), 2),
        "total_rmse": round(math.sqrt(mean(x * x for x in tresid)), 2),
        "fitted_total_sd": round(pstdev(tresid), 2), "total_bias": round(mean(tresid), 2),
        "calibration": [], "betting": None,
        "notes": "Ratings + situational only. Injury adjustments are not backtested.",
    }
    for lo in [i / 10 for i in range(10)]:
        b = [(p, y) for p, y in zip(ps, ys) if lo <= p < lo + 0.1]
        if b:
            report["calibration"].append({"bin": f"{lo:.0%}-{lo + 0.1:.0%}", "n": len(b),
                                          "predicted": round(mean(p for p, _ in b), 3),
                                          "actual": round(mean(y for _, y in b), 3)})
    if odds_rows:
        report["betting"] = _bet_sim(preds, odds_rows, sd, sdt, w, th)
    return report


def _bet_sim(preds, odds, sd, sdt, w, th):
    bets, market_ll, model_ll = [], [], []
    for g, p in preds:
        o = odds.get((g["et_date"], g["home"], g["away"]))
        if not o or "home_ml" not in o:
            continue
        margin = g["home_score"] - g["away_score"]
        total = g["home_score"] + g["away_score"]
        mh, _ = no_vig(o["home_ml"], o["away_ml"])
        y = 1 if margin > 0 else 0
        market_ll.append(-(y * math.log(mh) + (1 - y) * math.log(1 - mh)))
        pm = min(max(p["home_win_p"], 1e-4), 1 - 1e-4)
        model_ll.append(-(y * math.log(pm) + (1 - y) * math.log(1 - pm)))
        cands = []
        for side, pmod, pmk, price, won in (("home", pm, mh, o["home_ml"], margin > 0), ("away", 1 - pm, 1 - mh, o["away_ml"], margin < 0)):
            cands.append(("h2h", side, w * pmod + (1 - w) * pmk, pmk, price, 1 if won else -1))
        if {"home_spread", "home_spread_price", "away_spread_price"} <= o.keys():
            L = o["home_spread"]
            sh, _ = no_vig(o["home_spread_price"], o["away_spread_price"])
            pc = NORMAL.cdf((p["margin"] + L) / sd)
            x = margin + L
            res_h = 1 if x > 0 else 0 if x == 0 else -1
            cands.append(("spreads", "home", w * pc + (1 - w) * sh, sh, o["home_spread_price"], res_h))
            cands.append(("spreads", "away", w * (1 - pc) + (1 - w) * (1 - sh), 1 - sh, o["away_spread_price"], -res_h))
        if {"total", "over_price", "under_price"} <= o.keys():
            T = o["total"]
            so, _ = no_vig(o["over_price"], o["under_price"])
            po = NORMAL.cdf((p["total"] - T) / sdt)
            x = total - T
            res_o = 1 if x > 0 else 0 if x == 0 else -1
            cands.append(("totals", "over", w * po + (1 - w) * so, so, o["over_price"], res_o))
            cands.append(("totals", "under", w * (1 - po) + (1 - w) * (1 - so), 1 - so, o["under_price"], -res_o))
        for mkt, side, pb, pmk, price, res in cands:
            if pb - pmk >= th and pb * price > 1:
                profit = (price - 1) if res == 1 else -1.0 if res == -1 else 0.0
                bets.append({"market": mkt, "profit": profit})
    out = {"games_with_odds": len(market_ll),
           "model_log_loss_on_these": round(mean(model_ll), 4) if model_ll else None,
           "market_log_loss_on_these": round(mean(market_ll), 4) if market_ll else None,
           "bets": len(bets), "roi_flat": round(sum(b["profit"] for b in bets) / len(bets), 4) if bets else None,
           "by_market": {}}
    for m in ("h2h", "spreads", "totals"):
        mb = [b for b in bets if b["market"] == m]
        if mb:
            out["by_market"][m] = {"bets": len(mb), "roi_flat": round(sum(b["profit"] for b in mb) / len(mb), 4)}
    return out


def print_report(r):
    print(f"\nBacktest: {r['games']} games, seasons {r['seasons']}")
    print(f"  Log loss  {r['log_loss']}  (home-win-rate baseline {r['log_loss_baseline']}; lower is better)")
    print(f"  Brier     {r['brier']}   Accuracy {r['accuracy']:.1%}")
    print(f"  Margin    RMSE {r['margin_rmse']}  bias {r['margin_bias']:+}  -> set model.margin_sd to ~{r['fitted_margin_sd']}")
    print(f"  Total     RMSE {r['total_rmse']}  bias {r['total_bias']:+}  -> set model.total_sd to ~{r['fitted_total_sd']}")
    print("  Calibration (predicted vs actual home win %):")
    for c in r["calibration"]:
        print(f"    {c['bin']:>9}  n={c['n']:<5} predicted {c['predicted']:.1%}  actual {c['actual']:.1%}")
    b = r.get("betting")
    if b:
        print(f"  Betting vs your odds file: {b['bets']} bets, flat ROI {b['roi_flat']}")
        print(f"    Model log loss {b['model_log_loss_on_these']} vs market {b['market_log_loss_on_these']}"
              " (if the market is lower, it is better than the model)")
    else:
        print("  No odds file given: ROI vs closing lines not tested. See --odds-csv.")
    print(f"  Note: {r['notes']}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", type=int, nargs="+", help="seasons to test, by end year (2026 = 2025-26)")
    ap.add_argument("--odds-csv")
    ap.add_argument("--demo", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    paths = Paths()
    cfg = load_config(paths.config)
    now = utcnow()
    if args.demo:
        from .sources.demo import DemoSources
        games = DemoSources(cfg, now).games()
        seasons = args.seasons or [cfg["season"]["current"] - 1]
    else:
        from .sources.live import LiveSources
        seasons = args.seasons or [cfg["season"]["current"] - 1]
        needed = sorted({s for x in seasons for s in (x - 1, x)})
        games = LiveSources(cfg, paths, now).games(seasons=needed)
    report = run_backtest(cfg, games, set(seasons), load_odds_csv(args.odds_csv) if args.odds_csv else None)
    print_report(report)
    if not args.demo:
        save_json(paths.backtest, report)
        print(f"Saved to {paths.backtest} (shown on the Results page after the next update)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
