"""Player impact (on/off plus-minus), injury adjustments and projected lineups.

On/off = team's margin per 48 minutes with the player on court minus with him
off court, from this season's box scores, shrunk toward zero for small samples.

The key idea: team ratings already reflect who has been playing. So the
adjustment is  impact x (chance he plays today - share of recent games he played).
A star who has been out for weeks and is still out adds ~0 (already priced in);
a star ruled out tonight after playing every game subtracts his full impact;
a star returning tonight after missing games adds it back.
"""
from collections import defaultdict
from statistics import mean

from .util import clamp, norm_name


def compute_impacts(box, games_by_id, season, before, cfg):
    ic = cfg["injuries"]
    by_team = defaultdict(list)
    for gid, teams in box.items():
        g = games_by_id.get(gid)
        if not g or g["season"] != season or not g["completed"] or g["et_date"] >= before:
            continue
        for side, opp in (("home", "away"), ("away", "home")):
            rows = teams.get(g[side])
            if not rows:
                continue
            margin = g[f"{side}_score"] - g[f"{opp}_score"]
            team_min = sum(r["min"] for r in rows) / 5 or 48
            by_team[g[side]].append((g["et_date"], gid, rows, margin, team_min))

    impacts, meta = {}, {}
    for team, games in by_team.items():
        games.sort(key=lambda r: r[0])
        tot_margin = sum(r[3] for r in games)
        tot_min = sum(r[4] for r in games)
        recent = games[-ic["recent_games"]:]
        last3 = {p["id"] for r in games[-3:] for p in r[2]}
        acc = defaultdict(lambda: {"min": 0, "pm": 0, "name": "", "games": 0, "jersey": ""})
        for r in games:
            for p in r[2]:
                a = acc[p["id"]]
                a["min"] += p["min"]
                a["pm"] += p["pm"]
                a["name"] = p["name"]
                a["jersey"] = p.get("jersey") or a["jersey"]
                a["games"] += 1
        team_imp = {}
        for pid, a in acc.items():
            on48 = a["pm"] / a["min"] * 48 if a["min"] else 0.0
            off_min = tot_min - a["min"]
            off48 = (tot_margin - a["pm"]) / off_min * 48 if off_min >= 48 else tot_margin / tot_min * 48
            onoff = on48 - off48
            shrunk = onoff * a["min"] / (a["min"] + ic["prior_minutes"])
            mins = [p["min"] for r in recent for p in r[2] if p["id"] == pid]
            exp_min = mean(mins) if mins else a["min"] / max(1, a["games"])
            value = clamp(shrunk * exp_min / 48, -ic["max_player_impact"], ic["max_player_impact"])
            team_imp[pid] = {"name": a["name"], "jersey": a["jersey"], "minutes": a["min"], "onoff": round(onoff, 2),
                             "exp_min": round(exp_min, 1), "played_share": len(mins) / len(recent),
                             "value": value, "recent": pid in last3}
        impacts[team] = team_imp
        last = games[-1][2]
        meta[team] = {"last_starters": [p["id"] for p in last if p["starter"]], "games": len(games)}
    return impacts, meta


def _match(inj_list):
    by_id = {i["id"]: i for i in inj_list if i.get("id")}
    by_name = {norm_name(i["name"]): i for i in inj_list}
    return lambda pid, name: by_id.get(pid) or by_name.get(norm_name(name))


def team_injury_adjustment(team, impacts, injuries, cfg):
    """Returns (points adjustment for this team, injury rows for display)."""
    ic = cfg["injuries"]
    pprob = ic["play_probability"]
    imp = impacts.get(team, {})
    inj = injuries.get(team, [])
    find = _match(inj)
    total = 0.0
    matched = set()
    for pid, p in imp.items():
        i = find(pid, p["name"])
        if i:
            matched.add(id(i))
            p_today = pprob.get(i["status"], 0.5)
        elif p["recent"]:
            p_today = 1.0
        else:
            continue  # not seen lately and not on the report: already priced into ratings
        delta = p["value"] * (p_today - p["played_share"])
        p["_delta"] = delta
        total += delta
    rows = []
    for i in inj:
        p = next((v for k, v in imp.items() if (i.get("id") and k == i["id"]) or norm_name(v["name"]) == norm_name(i["name"])), None)
        delta = p.get("_delta", 0.0) if p else 0.0
        note = ""
        if p and p["played_share"] == 0 and i["status"] == "out":
            note = "Out for a while - already reflected in team ratings"
        elif not p:
            note = "No minutes this season"
        rows.append({"name": i["name"], "status": i["status"], "detail": i.get("detail", ""),
                     "impact": round(delta, 2), "exp_min": p["exp_min"] if p else 0, "note": note})
    rows.sort(key=lambda r: r["impact"])
    return clamp(total, -ic["max_team_adjust"], ic["max_team_adjust"]), rows


def projected_lineup(team, impacts, meta, injuries, cfg):
    pprob = cfg["injuries"]["play_probability"]
    imp = impacts.get(team, {})
    find = _match(injuries.get(team, []))

    def avail(pid):
        i = find(pid, imp[pid]["name"])
        return (pprob.get(i["status"], 0.5), i["status"]) if i else (1.0, "")

    lineup, out = [], []
    for pid in meta.get(team, {}).get("last_starters", []):
        if pid not in imp:
            continue
        p, status = avail(pid)
        if p >= 0.5:
            lineup.append({"name": imp[pid]["name"], "note": status if status not in ("", "available") else ""})
        else:
            out.append(imp[pid]["name"])
    bench = sorted((pid for pid in imp if pid not in meta.get(team, {}).get("last_starters", [])
                    and imp[pid]["recent"] and avail(pid)[0] >= 0.5), key=lambda pid: -imp[pid]["exp_min"])
    for pid, missing in zip(bench, out):
        lineup.append({"name": imp[pid]["name"], "note": f"in for {missing}"})
    return lineup[:5]


def team_roster(team, impacts, injuries, cfg, limit=13):
    """Rotation players with minutes, on/off impact and today's status, for the roster panel."""
    imp = impacts.get(team, {})
    find = _match(injuries.get(team, []))
    rows = []
    for pid, p in imp.items():
        inj = find(pid, p["name"])
        if not p["recent"] and not inj:
            continue  # not with the team lately (traded, waived, G League)
        rows.append({"name": p["name"], "jersey": p.get("jersey", ""), "mpg": p["exp_min"], "onoff": p["onoff"], "impact": round(p["value"], 2),
                     "played_share": round(p["played_share"], 2), "status": inj["status"] if inj else "available",
                     "detail": inj.get("detail", "") if inj else ""})
    rows.sort(key=lambda r: -r["mpg"])
    return rows[:limit]
