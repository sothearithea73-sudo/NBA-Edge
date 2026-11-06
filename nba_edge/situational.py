"""Rest, back-to-backs, 3-in-4, travel, time zones, altitude, neutral sites."""
from bisect import bisect_left
from collections import defaultdict
from datetime import timedelta

from .geo import TEAM_NAMES, is_altitude, km_between, tz_shift_hours


class Schedule:
    def __init__(self, games):
        self.by_team = defaultdict(list)
        for g in sorted(games, key=lambda g: g["tip"]):
            self.by_team[g["home"]].append(g)
            self.by_team[g["away"]].append(g)

    def context(self, team, game):
        lst = self.by_team[team]
        tips = [g["tip"] for g in lst]
        i = bisect_left(tips, game["tip"])
        prev = lst[i - 1] if i > 0 else None
        if prev and (game["et_date"] - prev["et_date"]).days > 20:
            prev = None  # off-season / long break
        rest = (game["et_date"] - prev["et_date"]).days - 1 if prev else 3
        window_start = game["et_date"] - timedelta(days=3)
        in4 = sum(1 for g in lst if window_start <= g["et_date"] <= game["et_date"])
        here = game["home"]
        km = km_between(prev["home"], here) if prev else 0.0
        tz = tz_shift_hours(prev["home"], here, game["tip"]) if prev else 0.0
        return {"rest": rest, "b2b": rest == 0, "three_in_four": in4 >= 3 and rest <= 1,
                "travel_km": round(km), "tz_shift": tz}


def adjustments(game, ctx_h, ctx_a, cfg, hca):
    """List of (label, points) from the home team's point of view."""
    sc = cfg["situational"]
    out = []
    H, A = game["home"], game["away"]
    for team, ctx, sign in ((H, ctx_h, 1), (A, ctx_a, -1)):
        if ctx["b2b"]:
            out.append((f"{team} on 2nd night of a back-to-back", sign * sc["back_to_back"]))
        if ctx["three_in_four"]:
            out.append((f"{team} playing 3rd game in 4 nights", sign * sc["three_in_four"]))
        if ctx["rest"] <= 1:
            if ctx["travel_km"] >= 500:
                out.append((f"{team} travelled {ctx['travel_km']:,} km on short rest", sign * sc["travel_per_1000km"] * ctx["travel_km"] / 1000))
            if ctx["tz_shift"] >= 1:
                out.append((f"{team} crossed {ctx['tz_shift']:.0f} time zone(s) on short rest", sign * sc["timezone_per_hour"] * ctx["tz_shift"]))
    cap = sc["rest_cap_days"]
    diff = min(ctx_h["rest"], cap) - min(ctx_a["rest"], cap)
    if diff:
        better = H if diff > 0 else A
        out.append((f"{better} has {abs(diff)} more day(s) of rest", diff * sc["rest_advantage_per_day"]))
    if is_altitude(H) and not is_altitude(A) and not game.get("neutral"):
        out.append((f"Altitude: {TEAM_NAMES.get(H, H)} at home", sc["altitude_home_bonus"]))
    if game.get("neutral"):
        out.append(("Neutral site: no home-court edge", -hca))
    return [(label, round(pts, 2)) for label, pts in out if abs(pts) >= 0.05]
