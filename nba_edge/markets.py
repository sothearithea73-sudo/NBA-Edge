"""Betting maths: remove the bookmaker margin, compare to the model, EV, Kelly, verdicts."""
from collections import Counter
from statistics import median

from .util import NORMAL, clamp


def no_vig(price_a, price_b):
    ia, ib = 1 / price_a, 1 / price_b
    return ia / (ia + ib), ib / (ia + ib)


def kelly(p, price):
    b = price - 1
    return max(0.0, (p * price - 1) / b) if b > 0 else 0.0


def cover_prob(side_margin, line, sd):
    """P(side_margin + line > 0) with margin ~ Normal(side_margin, sd)."""
    return NORMAL.cdf((side_margin + line) / sd)


def fair_at_line(market, side, close_line, close_p, bet_line, sd):
    """Translate a closing fair probability to the line you actually bet (for CLV)."""
    if market == "h2h" or close_line is None or bet_line is None or close_line == bet_line:
        return close_p
    z = NORMAL.inv_cdf(clamp(close_p, 1e-4, 1 - 1e-4))
    if market == "spreads":
        implied_margin = sd * z - close_line
        return NORMAL.cdf((implied_margin + bet_line) / sd)
    if side == "over":
        t = close_line + sd * z
        return NORMAL.cdf((t - bet_line) / sd)
    t = close_line - sd * z
    return NORMAL.cdf((bet_line - t) / sd)


def _side(name, label, line, p_model, rows, key_a, key_b, which, cfg):
    """Build one side of a two-way market from book rows."""
    fair = []
    best = (0.0, None)
    for r in rows:
        pa, pb = no_vig(r[key_a], r[key_b])
        fair.append(pa if which == 0 else pb)
        price = r[key_a] if which == 0 else r[key_b]
        if price > best[0]:
            best = (price, r["book"])
    mkt = median(fair)
    w = cfg["model"]["model_weight"]
    blend = w * p_model + (1 - w) * mkt
    price, book = best
    return {"side": name, "label": label, "line": line, "model_p": round(p_model, 4), "market_p": round(mkt, 4),
            "blend_p": round(blend, 4), "edge": round(blend - mkt, 4), "best_price": price, "best_book": book,
            "ev": round(blend * price - 1, 4), "kelly": round(kelly(blend, price), 4), "n_books": len(rows)}


def _modal(rows, key):
    if not rows:
        return None, []
    c = Counter(r[key] for r in rows)
    top = max(c.values())
    line = sorted((k for k, v in c.items() if v == top), key=abs)[0]
    return line, [r for r in rows if r[key] == line]


def evaluate(game, proj, odds_game, cfg):
    """Return the list of market dicts for one game."""
    if not odds_game:
        return []
    sd, sdt = cfg["model"]["margin_sd"], cfg["model"]["total_sd"]
    H, A = game["home"], game["away"]
    m, tot = proj["margin"], proj["total"]
    markets = []
    if odds_game["h2h"]:
        p = NORMAL.cdf(m / sd)
        rows = odds_game["h2h"]
        markets.append({"market": "h2h", "title": "Moneyline", "sides": [
            _side("home", H, None, p, rows, "home", "away", 0, cfg),
            _side("away", A, None, 1 - p, rows, "home", "away", 1, cfg)]})
    line, rows = _modal(odds_game["spreads"], "home_point")
    if rows:
        p = cover_prob(m, line, sd)
        markets.append({"market": "spreads", "title": "Spread", "sides": [
            _side("home", f"{H} {line:+g}", line, p, rows, "home", "away", 0, cfg),
            _side("away", f"{A} {-line:+g}", -line, 1 - p, rows, "home", "away", 1, cfg)]})
    line, rows = _modal(odds_game["totals"], "point")
    if rows:
        p = NORMAL.cdf((tot - line) / sdt)
        markets.append({"market": "totals", "title": "Total", "sides": [
            _side("over", f"Over {line:g}", line, p, rows, "over", "under", 0, cfg),
            _side("under", f"Under {line:g}", line, 1 - p, rows, "over", "under", 1, cfg)]})
    return markets


def decide(markets, cfg, block_reason=None):
    """Attach a verdict to each market (mutates). Returns the markets."""
    bc = cfg["betting"]
    th = bc["edge_threshold"]
    for mk in markets:
        best = max(mk["sides"], key=lambda s: s["edge"])
        verdict, stake = "Pass", 0.0
        reason = ""
        if block_reason:
            verdict, reason = "No pick", block_reason
        elif best["n_books"] < bc["min_books"]:
            verdict, reason = "No pick", f"only {best['n_books']} bookmaker(s) priced this"
        elif best["edge"] >= th and best["ev"] > 0:
            verdict = "Value bet"
            stake = min(bc["kelly_fraction"] * best["kelly"], bc["max_stake_pct"])
        elif best["edge"] >= th * bc["lean_fraction"] and best["ev"] > 0:
            verdict = "Lean"
        mk["pick"] = {"side": best["side"], "label": best["label"], "line": best["line"], "verdict": verdict,
                      "edge": best["edge"], "ev": best["ev"], "price": best["best_price"], "book": best["best_book"],
                      "stake_pct": round(stake, 4), "reason": reason}
    if bc.get("one_bet_per_game"):
        values = [mk for mk in markets if mk["pick"]["verdict"] == "Value bet"]
        if len(values) > 1:
            keep = max(values, key=lambda mk: mk["pick"]["ev"])
            for mk in values:
                if mk is not keep:
                    mk["pick"].update(verdict="Lean", stake_pct=0.0, reason="another bet on this game was stronger")
    return markets


def cap_exposure(games_out, cfg):
    """Scale every stake down so one day's total stays under the limit."""
    limit = cfg["betting"]["max_daily_exposure_pct"]
    picks = [mk["pick"] for g in games_out for mk in g["markets"] if mk["pick"]["stake_pct"] > 0]
    total = sum(p["stake_pct"] for p in picks)
    if total > limit:
        f = limit / total
        for p in picks:
            p["stake_pct"] = round(p["stake_pct"] * f, 4)
        return round(f, 3)
    return 1.0
