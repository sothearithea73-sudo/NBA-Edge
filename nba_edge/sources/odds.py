"""The Odds API (https://the-odds-api.com): bookmaker prices.

Cost: each call uses (number of markets x number of regions) credits.
Default = 3 markets x 1 region (au) = 3 credits. Free plan = 500 credits/month.
"""
from datetime import timedelta

import requests

from ..geo import TEAM_NAMES
from ..util import norm_name, parse_dt
from .espn import SourceError

ODDS_URL = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"


def fetch_odds(api_key, regions, markets):
    if not api_key:
        raise SourceError("ODDS_API_KEY is not set (add it as a GitHub repository Secret)")
    try:
        r = requests.get(ODDS_URL, timeout=25, params={
            "apiKey": api_key, "regions": regions, "markets": markets,
            "oddsFormat": "decimal", "dateFormat": "iso"})
    except requests.RequestException as e:
        raise SourceError(f"Odds API unreachable: {e}") from e
    if r.status_code == 401:
        raise SourceError("Odds API rejected the key (HTTP 401) - check the ODDS_API_KEY secret")
    if r.status_code == 429:
        raise SourceError("Odds API quota used up (HTTP 429) - wait for the monthly reset or upgrade")
    if r.status_code != 200:
        raise SourceError(f"Odds API HTTP {r.status_code}")
    meta = {"remaining": r.headers.get("x-requests-remaining"), "used": r.headers.get("x-requests-used")}
    return r.json(), meta


def _name_index(games):
    idx = {norm_name(v): k for k, v in TEAM_NAMES.items()}
    for g in games:
        idx[norm_name(g["home_name"])] = g["home"]
        idx[norm_name(g["away_name"])] = g["away"]
    return idx


def parse_odds(events, games):
    """Match Odds API events to our games. Returns {game_id: odds_game}.

    odds_game = {
      "h2h":     [{book, home, away}],                       # decimal prices
      "spreads": [{book, home_point, home, away_point, away}],
      "totals":  [{book, point, over, under}],
      "last_update": iso string }
    """
    names = _name_index(games)
    out = {}
    for ev in events or []:
        h, a = names.get(norm_name(ev.get("home_team"))), names.get(norm_name(ev.get("away_team")))
        if not h or not a:
            continue
        try:
            start = parse_dt(ev["commence_time"])
        except (KeyError, ValueError):
            continue
        game = next((g for g in games if g["home"] == h and g["away"] == a
                     and abs(g["tip"] - start) < timedelta(hours=4)), None)
        if not game:
            continue
        home_n, away_n = norm_name(ev["home_team"]), norm_name(ev["away_team"])
        og = {"h2h": [], "spreads": [], "totals": [], "last_update": None}
        for bk in ev.get("bookmakers", []):
            book = bk.get("title") or bk.get("key")
            lu = bk.get("last_update")
            if lu and (og["last_update"] is None or lu > og["last_update"]):
                og["last_update"] = lu
            for m in bk.get("markets", []):
                oc = {norm_name(o.get("name")): o for o in m.get("outcomes", [])}
                try:
                    if m["key"] == "h2h" and home_n in oc and away_n in oc:
                        og["h2h"].append({"book": book, "home": float(oc[home_n]["price"]), "away": float(oc[away_n]["price"])})
                    elif m["key"] == "spreads" and home_n in oc and away_n in oc:
                        og["spreads"].append({"book": book, "home_point": float(oc[home_n]["point"]), "home": float(oc[home_n]["price"]),
                                              "away_point": float(oc[away_n]["point"]), "away": float(oc[away_n]["price"])})
                    elif m["key"] == "totals" and "over" in oc and "under" in oc:
                        og["totals"].append({"book": book, "point": float(oc["over"]["point"]),
                                             "over": float(oc["over"]["price"]), "under": float(oc["under"]["price"])})
                except (KeyError, TypeError, ValueError):
                    continue
        out[game["id"]] = og
    return out
