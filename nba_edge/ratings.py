"""Opponent-adjusted team ratings from game scores.

Each game gives two equations:
  home points = league avg + home court + home offence - away defence
  away points = league avg            + away offence - home defence
Solved by weighted ridge regression: recent games count more (half-life),
last season counts less and fades out as this season goes on.
"""
from dataclasses import dataclass, field

import numpy as np


@dataclass
class Ratings:
    off: dict = field(default_factory=dict)   # points per game above average (higher = better offence)
    deff: dict = field(default_factory=dict)  # points per game prevented (higher = better defence)
    mu: float = 113.0
    hca: float = 2.0
    n_games: int = 0

    def project(self, home, away, neutral=False):
        h = self.mu + (0.0 if neutral else self.hca) + self.off.get(home, 0.0) - self.deff.get(away, 0.0)
        a = self.mu + self.off.get(away, 0.0) - self.deff.get(home, 0.0)
        return h, a

    def net(self, team):
        return self.off.get(team, 0.0) + self.deff.get(team, 0.0)


def fit_ratings(games, before, cfg, current_season):
    rc = cfg["ratings"]
    played = [g for g in games if g["completed"] and g["et_date"] < before]
    if len(played) < 20:
        return Ratings(n_games=len(played))
    teams = sorted({g["home"] for g in played} | {g["away"] for g in played})
    idx = {t: i for i, t in enumerate(teams)}
    n, m = len(teams), len(played)
    p = 2 + 2 * n

    cur = [g["et_date"] for g in played if g["season"] == current_season]
    prev = [g["et_date"] for g in played if g["season"] != current_season]
    cur_start = min(cur) if cur else before
    prev_end = max(prev) if prev else before
    days_into_season = max(0, (before - cur_start).days) if cur else 0
    hl = rc["half_life_days"]

    X = np.zeros((2 * m, p))
    y = np.zeros(2 * m)
    w = np.zeros(2 * m)
    for k, g in enumerate(played):
        if g["season"] == current_season or not cur:
            wt = 0.5 ** ((before - g["et_date"]).days / hl)
        else:
            # last season: decay within that season, then fade as this season goes on (no decay over the summer)
            wt = rc["previous_season_weight"] * 0.5 ** ((prev_end - g["et_date"]).days / hl) * 0.5 ** (days_into_season / hl)
        h, a = idx[g["home"]], idx[g["away"]]
        r = 2 * k
        X[r, 0] = 1
        X[r, 1] = 0 if g.get("neutral") else 1
        X[r, 2 + h] = 1
        X[r, 2 + n + a] = -1
        y[r], w[r] = g["home_score"], wt
        X[r + 1, 0] = 1
        X[r + 1, 2 + a] = 1
        X[r + 1, 2 + n + h] = -1
        y[r + 1], w[r + 1] = g["away_score"], wt

    A = X.T @ (X * w[:, None])
    b = X.T @ (w * y)
    reg = np.full(p, float(rc["ridge_lambda"]))
    reg[:2] = 1e-6
    beta = np.linalg.solve(A + np.diag(reg), b)
    return Ratings(
        off={t: float(beta[2 + i]) for t, i in idx.items()},
        deff={t: float(beta[2 + n + i]) for t, i in idx.items()},
        mu=float(beta[0]), hca=float(beta[1]), n_games=m,
    )
