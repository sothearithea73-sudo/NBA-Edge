"""Combine ratings + situational + injuries into a projection for one game."""
from collections import defaultdict

from .util import NORMAL


def project_game(game, ratings, sched, inj_adj_h, inj_adj_a, cfg, situational_mod):
    mc = cfg["model"]
    share = cfg["injuries"]["offense_share"]
    H, A = game["home"], game["away"]
    base_h, base_a = ratings.project(H, A)
    adj = situational_mod.adjustments(game, sched.context(H, game), sched.context(A, game), cfg, ratings.hca)
    sit = sum(p for _, p in adj)
    home_pts = base_h + sit / 2 + inj_adj_h * share - inj_adj_a * (1 - share)
    away_pts = base_a - sit / 2 + inj_adj_a * share - inj_adj_h * (1 - share)
    if abs(inj_adj_h) >= 0.05:
        adj.append((f"{H} injuries / lineup", round(inj_adj_h, 2)))
    if abs(inj_adj_a) >= 0.05:
        adj.append((f"{A} injuries / lineup", round(-inj_adj_a, 2)))
    margin = home_pts - away_pts
    total = home_pts + away_pts
    z = NORMAL.inv_cdf(0.5 + mc["uncertainty_interval"] / 2)
    return {
        "base_margin": round(base_h - base_a, 2), "home_court": round(ratings.hca, 2),
        # pts is from the home side's view; "favours" says which team it helps
        "adjustments": [{"label": l, "pts": p, "favours": H if p > 0 else A, "size": round(abs(p), 2)} for l, p in adj],
        "margin": round(margin, 2), "total": round(total, 1),
        "home_pts": round(home_pts, 1), "away_pts": round(away_pts, 1),
        "margin_lo": round(margin - z * mc["margin_sd"], 1), "margin_hi": round(margin + z * mc["margin_sd"], 1),
        "total_lo": round(total - z * mc["total_sd"], 1), "total_hi": round(total + z * mc["total_sd"], 1),
        "home_win_p": round(NORMAL.cdf(margin / mc["margin_sd"]), 4),
        "interval": mc["uncertainty_interval"],
    }


def team_stats(games, box, season, before, ratings):
    """Record, last-10 form, and possession-based ratings from box scores."""
    res = defaultdict(lambda: {"w": 0, "l": 0, "log": [], "poss": 0.0, "pf": 0, "pa": 0, "bx": 0})
    for g in games:
        if g["season"] != season or not g["completed"] or g["et_date"] >= before:
            continue
        b = box.get(g["id"])
        poss = None
        if b and g["home"] in b and g["away"] in b:
            est = [sum(p["fga"] - p["oreb"] + p["tov"] + 0.44 * p["fta"] for p in b[t]) for t in (g["home"], g["away"])]
            poss = sum(est) / 2
        for side, opp in (("home", "away"), ("away", "home")):
            t = res[g[side]]
            m = g[f"{side}_score"] - g[f"{opp}_score"]
            t["w" if m > 0 else "l"] += 1
            t["log"].append((g["et_date"], m))
            if poss:
                t["poss"] += poss
                t["pf"] += g[f"{side}_score"]
                t["pa"] += g[f"{opp}_score"]
                t["bx"] += 1
    out = {}
    for team, t in res.items():
        last = [m for _, m in sorted(t["log"])[-10:]]
        out[team] = {
            "record": f"{t['w']}-{t['l']}",
            "last10": f"{sum(m > 0 for m in last)}-{sum(m <= 0 for m in last)}",
            "last10_margin": round(sum(last) / len(last), 1) if last else 0.0,
            "pace": round(t["poss"] / t["bx"], 1) if t["bx"] else None,
            "ortg": round(t["pf"] / t["poss"] * 100, 1) if t["poss"] else None,
            "drtg": round(t["pa"] / t["poss"] * 100, 1) if t["poss"] else None,
            "adj_off": round(ratings.off.get(team, 0.0), 1), "adj_def": round(ratings.deff.get(team, 0.0), 1),
            "adj_net": round(ratings.net(team), 1), "games": t["w"] + t["l"],
        }
    return out
