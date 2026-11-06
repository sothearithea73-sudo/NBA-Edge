"""ESPN's public JSON feeds: schedule & scores, box scores, injuries.

These are free and need no key, but they are unofficial: ESPN can change the
format without notice. Every parser here is defensive and raises SourceError
with a clear message instead of crashing on an odd response.
"""
import logging
import re
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests

from ..geo import ARENAS, canon_abbr
from ..util import norm_name, season_of

log = logging.getLogger(__name__)
BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; nba-edge personal research project)"}
ET = ZoneInfo("America/New_York")
VALID_SEASON_TYPES = {2, 3, 5}  # regular season, playoffs, play-in (skips preseason / All-Star)


class SourceError(RuntimeError):
    pass


def get_json(url, params=None, tries=3, timeout=25):
    last = None
    for attempt in range(tries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            last = f"HTTP {r.status_code}"
        except (requests.RequestException, ValueError) as e:
            last = str(e)
        time.sleep(1.5 * (attempt + 1))
    raise SourceError(f"{url} failed after {tries} tries ({last})")


def _int(x, default=0):
    s = str(x if x is not None else "").replace("+", "").strip()
    if ":" in s:
        s = s.split(":")[0]
    try:
        return int(float(s))
    except ValueError:
        return default


def _pair(s):
    try:
        a, b = str(s).split("-")
        return _int(a), _int(b)
    except ValueError:
        return 0, 0


def parse_event(ev):
    try:
        comp = ev["competitions"][0]
        sides = {c["homeAway"]: c for c in comp["competitors"]}
        home, away = sides["home"], sides["away"]
        tip = datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
    except (KeyError, IndexError, ValueError, TypeError):
        return None
    if tip.tzinfo is None:
        tip = tip.replace(tzinfo=timezone.utc)
    h = canon_abbr(home["team"].get("abbreviation"))
    a = canon_abbr(away["team"].get("abbreviation"))
    if h not in ARENAS or a not in ARENAS:
        return None
    stype = (ev.get("season") or {}).get("type")
    if stype is not None and stype not in VALID_SEASON_TYPES:
        return None
    st = ((comp.get("status") or ev.get("status") or {}).get("type")) or {}
    et_date = tip.astimezone(ET).date()
    return {
        "id": str(ev["id"]), "tip": tip, "et_date": et_date, "season": season_of(et_date),
        "home": h, "away": a,
        "home_name": home["team"].get("displayName", h),
        "away_name": away["team"].get("displayName", a),
        "home_score": _int(home.get("score")), "away_score": _int(away.get("score")),
        "state": st.get("state", "pre"), "completed": bool(st.get("completed")),
        "status_text": st.get("shortDetail") or st.get("description", ""),
        "neutral": bool(comp.get("neutralSite", False)),
    }


def fetch_scoreboard(start, end):
    data = get_json(f"{BASE}/scoreboard", {"dates": f"{start:%Y%m%d}-{end:%Y%m%d}", "limit": 1000})
    games = [g for g in (parse_event(e) for e in data.get("events", [])) if g]
    return games


_LABEL_TO_KEY = {"MIN": "minutes", "PTS": "points", "+/-": "plusMinus", "FG": "fieldGoalsMade-fieldGoalsAttempted",
                 "FT": "freeThrowsMade-freeThrowsAttempted", "OREB": "offensiveRebounds", "TO": "turnovers"}


def fetch_box(event_id):
    """Return {team_abbr: [player rows]} for a finished game."""
    data = get_json(f"{BASE}/summary", {"event": event_id})
    teams = {}
    for block in (data.get("boxscore") or {}).get("players", []):
        abbr = canon_abbr((block.get("team") or {}).get("abbreviation"))
        stats = (block.get("statistics") or [{}])[0]
        keys = stats.get("keys") or [_LABEL_TO_KEY.get(n, n) for n in (stats.get("names") or stats.get("labels") or [])]
        rows = []
        for ath in stats.get("athletes", []):
            if ath.get("didNotPlay"):
                continue
            v = dict(zip(keys, ath.get("stats", [])))
            mins = _int(v.get("minutes"))
            if mins <= 0:
                continue
            person = ath.get("athlete") or {}
            rows.append({
                "id": str(person.get("id", "")), "name": person.get("displayName", "?"),
                "min": mins, "pm": _int(v.get("plusMinus")), "starter": bool(ath.get("starter")),
                "jersey": str(person.get("jersey") or ""),
                "pts": _int(v.get("points")),
                "fga": _pair(v.get("fieldGoalsMade-fieldGoalsAttempted"))[1],
                "fta": _pair(v.get("freeThrowsMade-freeThrowsAttempted"))[1],
                "oreb": _int(v.get("offensiveRebounds")), "tov": _int(v.get("turnovers")),
            })
        if abbr and rows:
            teams[abbr] = rows
    if len(teams) != 2:
        raise SourceError(f"box score {event_id}: expected 2 teams, got {len(teams)} (format may have changed)")
    return teams


def normalize_status(raw):
    s = (raw or "").lower()
    if "suspen" in s:
        return "out"
    if "doubt" in s:
        return "doubtful"
    if "question" in s or "gtd" in s or "game-time" in s or "game time" in s:
        return "questionable"
    if "probable" in s:
        return "probable"
    if "out" in s:
        return "out"
    if "day-to-day" in s or "day to day" in s:
        return "day-to-day"
    if "available" in s or "active" in s:
        return "available"
    return "questionable"


def _id_from_links(links):
    for link in links or []:
        m = re.search(r"/id/(\d+)", link.get("href", ""))
        if m:
            return m.group(1)
    return ""


def fetch_injuries(name_to_abbr):
    """Return {team_abbr: [{id, name, status, status_raw, detail}]}."""
    data = get_json(f"{BASE}/injuries")
    if "injuries" not in data:
        raise SourceError("injury feed: unexpected format (no 'injuries' key)")
    out = {}
    for team in data.get("injuries", []):
        team_abbr = name_to_abbr.get(norm_name(team.get("displayName", "")))
        for item in team.get("injuries", []):
            ath = item.get("athlete") or {}
            abbr = team_abbr or canon_abbr((ath.get("team") or {}).get("abbreviation"))
            if abbr not in ARENAS:
                continue
            details = item.get("details") or {}
            fantasy = (details.get("fantasyStatus") or {}).get("description", "")
            raw = " ".join(x for x in [item.get("status", ""), fantasy] if x)
            out.setdefault(abbr, []).append({
                "id": str(ath.get("id") or _id_from_links(ath.get("links"))),
                "name": ath.get("displayName", "?"),
                "status": normalize_status(raw), "status_raw": item.get("status", ""),
                "detail": item.get("shortComment") or details.get("type", "") or "",
            })
    return out
