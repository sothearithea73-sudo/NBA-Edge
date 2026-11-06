"""Pick log: records every Value bet, tracks closing line value, grades results.

Units: 1 unit = 1% of bankroll. A stake of 1.5% = 1.5 units.
CLV = (price you got x closing fair probability) - 1. Positive CLV over many
bets is the best early sign the model has a real edge.
"""
from collections import defaultdict

from .markets import fair_at_line


def _sd(cfg, market):
    return cfg["model"]["total_sd"] if market == "totals" else cfg["model"]["margin_sd"]


def update(hist, games_out, games_by_id, now, cfg):
    picks = hist.setdefault("picks", {})
    for g in games_out:
        if g["state"] != "pre":
            continue
        for mk in g["markets"]:
            sides = {s["side"]: s for s in mk["sides"]}
            # refresh the "closing" snapshot for anything already logged on this game
            for side, s in sides.items():
                p = picks.get(f"{g['id']}:{mk['market']}:{side}")
                if p and p["result"] is None:
                    p["close_line"], p["close_fair_p"], p["close_price"] = s["line"], s["market_p"], s["best_price"]
                    p["close_at"] = now.isoformat()
            pk = mk["pick"]
            if pk["verdict"] != "Value bet":
                continue
            pid = f"{g['id']}:{mk['market']}:{pk['side']}"
            if pid in picks:
                continue
            s = sides[pk["side"]]
            picks[pid] = {
                "id": pid, "game_id": g["id"], "date": g["et_date"], "tip": g["tip_utc"],
                "matchup": f"{g['away']['abbr']} @ {g['home']['abbr']}", "market": mk["market"], "side": pk["side"],
                "label": pk["label"], "line": pk["line"], "price": pk["price"], "book": pk["book"],
                "model_p": s["model_p"], "blend_p": s["blend_p"], "fair_p": s["market_p"], "edge": pk["edge"],
                "ev": pk["ev"], "stake_pct": pk["stake_pct"], "flagged_at": now.isoformat(),
                "close_line": s["line"], "close_fair_p": s["market_p"], "close_price": s["best_price"],
                "close_at": now.isoformat(), "result": None, "profit_units": None, "clv": None,
            }
    for p in picks.values():
        if p["result"] is not None:
            continue
        g = games_by_id.get(p["game_id"])
        if g and g["completed"]:
            grade(p, g, cfg)
    return hist


def grade(p, g, cfg):
    margin = g["home_score"] - g["away_score"]
    total = g["home_score"] + g["away_score"]
    if p["market"] == "h2h":
        won = margin > 0 if p["side"] == "home" else margin < 0
        res = "win" if won else "loss"
    elif p["market"] == "spreads":
        x = (margin if p["side"] == "home" else -margin) + p["line"]
        res = "win" if x > 0 else "push" if x == 0 else "loss"
    else:
        x = (total - p["line"]) if p["side"] == "over" else (p["line"] - total)
        res = "win" if x > 0 else "push" if x == 0 else "loss"
    units = p["stake_pct"] * 100
    p["result"] = res
    p["final"] = f"{g['away']} {g['away_score']} - {g['home']} {g['home_score']}"
    p["profit_units"] = round(units * (p["price"] - 1) if res == "win" else -units if res == "loss" else 0.0, 3)
    p["flat_profit"] = round((p["price"] - 1) if res == "win" else -1.0 if res == "loss" else 0.0, 3)
    close_p = fair_at_line(p["market"], p["side"], p["close_line"], p["close_fair_p"], p["line"], _sd(cfg, p["market"]))
    p["clv"] = round(p["price"] * close_p - 1, 4)


def _summarise(rows):
    graded = [p for p in rows if p["result"] is not None]
    w = sum(p["result"] == "win" for p in graded)
    l_ = sum(p["result"] == "loss" for p in graded)
    pu = sum(p["result"] == "push" for p in graded)
    staked = sum(p["stake_pct"] * 100 for p in graded if p["result"] != "push")
    profit = sum(p["profit_units"] for p in graded)
    flat = sum(p["flat_profit"] for p in graded)
    flat_n = sum(p["result"] != "push" for p in graded)
    clvs = [p["clv"] for p in graded if p["clv"] is not None]
    return {"bets": len(graded), "pending": len(rows) - len(graded), "wins": w, "losses": l_, "pushes": pu,
            "staked_units": round(staked, 2), "profit_units": round(profit, 2),
            "roi": round(profit / staked, 4) if staked else None,
            "flat_roi": round(flat / flat_n, 4) if flat_n else None,
            "avg_clv": round(sum(clvs) / len(clvs), 4) if clvs else None,
            "beat_close_pct": round(sum(c > 0 for c in clvs) / len(clvs), 3) if clvs else None}


def summary(hist):
    picks = sorted(hist.get("picks", {}).values(), key=lambda p: p["tip"], reverse=True)
    by_market = defaultdict(list)
    for p in picks:
        by_market[p["market"]].append(p)
    return {"overall": _summarise(picks), "by_market": {k: _summarise(v) for k, v in by_market.items()}, "picks": picks}
