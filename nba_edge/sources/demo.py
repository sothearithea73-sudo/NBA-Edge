"""Invented data with the same shape as the live feeds.

Used for tests and for previewing the website without API keys. Nothing here
is real: player names, injuries and odds are all made up.
"""
import random
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ..geo import ARENAS, TEAM_NAMES
from ..util import NORMAL, season_of

ET = ZoneInfo("America/New_York")
FIRST = ["Jalen", "Marcus", "Tyrese", "Devin", "Andre", "Malik", "Cole", "Isaiah", "Jordan", "Theo", "Luca", "Kai",
         "Darius", "Evan", "Noah", "Miles", "Zion", "Caleb", "Owen", "Reggie"]
LAST = ["Carter", "Hayes", "Brooks", "Ellison", "Moreau", "Okafor", "Lindqvist", "Grant", "Whitaker", "Navarro",
        "Fields", "Duarte", "Kimura", "Bishop", "Vance", "Odum", "Petrov", "Sterling", "Achebe", "Rowe"]
MINUTES = [35, 34, 32, 30, 28, 23, 20, 16, 13, 9]
BOOKS = ["Sportsbet", "TAB", "Ladbrokes", "Neds", "PointsBet (AU)"]


class DemoSources:
    name = "demo"

    def __init__(self, cfg, now, seed=11):
        self.cfg, self.now = cfg, now
        rng = self.rng = random.Random(seed)
        self.teams = list(ARENAS)
        self.true = {t: (rng.gauss(0, 3.2), rng.gauss(0, 3.2)) for t in self.teams}
        self.players = {}
        pid = 1000
        for t in self.teams:
            roster = []
            numbers = rng.sample([0, 1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 12, 13, 14, 15, 17, 20, 21, 22, 23, 24, 25, 30, 32, 33, 35, 42, 55, 77], len(MINUTES))
            for i, mins in enumerate(MINUTES):
                pid += 1
                roster.append({"id": str(pid), "name": f"{rng.choice(FIRST)} {rng.choice(LAST)}", "min": mins, "jersey": str(numbers[i]),
                               "impact": rng.gauss(4.0 if i < 2 else 1.0 if i < 5 else -0.5, 1.5)})
            self.players[t] = roster
        today = now.astimezone(ET).date()
        # injuries: a long-term absence, plus fresh news on a few teams
        self.inj = {}
        for t in rng.sample(self.teams, 12):
            p = rng.choice(self.players[t][5:])
            self.inj.setdefault(t, []).append((p, "out", "Knee - out indefinitely", today - timedelta(days=25)))
        for t, status in zip(rng.sample(self.teams, 9), ["out", "out", "questionable", "questionable", "doubtful",
                                                          "probable", "day-to-day", "out", "questionable"]):
            p = rng.choice(self.players[t][:3])
            self.inj.setdefault(t, []).append((p, status, rng.choice(["Ankle sprain", "Hamstring tightness", "Illness",
                                                                         "Calf soreness", "Rest"]), today))
        self._games = self._make_games(today)

    def _out_on(self, team, d):
        return {p["id"] for p, st, _, since in self.inj.get(team, []) if since <= d and st == "out"}

    def _make_games(self, today):
        rng, cur = self.rng, self.cfg["season"]["current"]
        games, gid = [], 400000000
        spans = [(date(cur - 2, 10, 22), date(cur - 1, 4, 12)), (date(cur - 1, 10, 21), today + timedelta(days=2))]
        for start, end in spans:
            d = start
            while d <= end:
                teams = rng.sample(self.teams, rng.choice([8, 10, 12, 14, 16]))
                for i in range(0, len(teams), 2):
                    h, a = teams[i], teams[i + 1]
                    gid += 1
                    hour, minute = rng.choice([(19, 0), (19, 0), (19, 30), (20, 0), (22, 0)])
                    tip = datetime(d.year, d.month, d.day, hour, minute, tzinfo=ET).astimezone(timezone.utc)
                    done = d < today
                    hs = as_ = 0
                    if done:
                        oh, dh = self.true[h]
                        oa, da = self.true[a]
                        hs = round(113 + 2.2 + oh - da + rng.gauss(0, 9))
                        as_ = round(113 + oa - dh + rng.gauss(0, 9))
                        if hs == as_:
                            hs += 1
                    games.append({"id": str(gid), "tip": tip, "et_date": d, "season": season_of(d), "home": h, "away": a,
                                  "home_name": TEAM_NAMES[h], "away_name": TEAM_NAMES[a], "home_score": hs, "away_score": as_,
                                  "state": "post" if done else "pre", "completed": done,
                                  "status_text": "Final" if done else tip.astimezone(ET).strftime("%-I:%M %p ET"),
                                  "neutral": False})
                d += timedelta(days=1)
        return games

    def games(self, seasons=None):
        return list(self._games)

    def box_scores(self, games):
        rng, cur = self.rng, self.cfg["season"]["current"]
        box = {}
        for g in self._games:
            if not g["completed"] or g["season"] != cur:
                continue
            teams = {}
            for side, opp in (("home", "away"), ("away", "home")):
                t = g[side]
                margin = g[f"{side}_score"] - g[f"{opp}_score"]
                out = self._out_on(t, g["et_date"])
                roster = [p for p in self.players[t] if p["id"] not in out]
                scale = 240 / sum(p["min"] for p in roster)
                rows = []
                for i, p in enumerate(roster):
                    mins = max(1, round(p["min"] * scale + rng.gauss(0, 2)))
                    rows.append({"id": p["id"], "name": p["name"], "min": mins, "starter": i < 5, "jersey": p["jersey"],
                                 "pm": round(margin * mins / 48 + p["impact"] * mins / 48 + rng.gauss(0, 4)),
                                 "pts": max(0, round(mins * 0.5 + rng.gauss(0, 4))), "fga": round(mins * 0.37),
                                 "fta": round(mins * 0.1), "oreb": round(mins * 0.04), "tov": round(mins * 0.06)})
                teams[t] = rows
            box[g["id"]] = teams
        return box

    def injuries(self, name_to_abbr):
        return {t: [{"id": p["id"], "name": p["name"], "status": st, "status_raw": st.title(), "detail": det}
                    for p, st, det, _ in rows] for t, rows in self.inj.items()}

    def odds(self):
        rng = self.rng
        events = []
        today = self.now.astimezone(ET).date()
        pprob = self.cfg["injuries"]["play_probability"]
        for g in self._games:
            if g["completed"] or g["et_date"] > today + timedelta(days=1):
                continue
            h, a = g["home"], g["away"]
            oh, dh = self.true[h]
            oa, da = self.true[a]

            def inj_cost(t):
                return sum(p["impact"] * p["min"] / 48 * (1 - pprob.get(st, 0.5))
                           for p, st, _, since in self.inj.get(t, []) if since == today)
            mkt_margin = 2.2 + (oh + dh) - (oa + da) - inj_cost(h) + inj_cost(a) + rng.gauss(0, 1.6)
            mkt_total = 226 + oh + oa - dh - da + rng.gauss(0, 3)
            line = -round(mkt_margin * 2) / 2
            tline = round(mkt_total * 2) / 2
            ph = NORMAL.cdf(mkt_margin / 12.5)
            pc = NORMAL.cdf((mkt_margin + line) / 12.5)
            po = NORMAL.cdf((mkt_total - tline) / 18)
            bms = []
            for book in rng.sample(BOOKS, 4):
                vig = 1.045 + rng.uniform(-0.01, 0.01)

                def px(p):
                    return round(max(1.01, 1 / (min(0.97, max(0.03, p + rng.gauss(0, 0.012))) * vig)), 2)
                bms.append({"key": book.lower(), "title": book, "last_update": self.now.isoformat(), "markets": [
                    {"key": "h2h", "outcomes": [{"name": TEAM_NAMES[h], "price": px(ph)}, {"name": TEAM_NAMES[a], "price": px(1 - ph)}]},
                    {"key": "spreads", "outcomes": [{"name": TEAM_NAMES[h], "price": px(pc), "point": line},
                                                    {"name": TEAM_NAMES[a], "price": px(1 - pc), "point": -line}]},
                    {"key": "totals", "outcomes": [{"name": "Over", "price": px(po), "point": tline},
                                                   {"name": "Under", "price": px(1 - po), "point": tline}]}]})
            events.append({"id": f"demo{g['id']}", "commence_time": g["tip"].isoformat(), "home_team": TEAM_NAMES[h],
                           "away_team": TEAM_NAMES[a], "bookmakers": bms})
        return events, {"remaining": "demo"}
