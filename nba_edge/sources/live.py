"""Live data with caching, so finished months and box scores are fetched once."""
import logging
import os
import time
from datetime import date, timedelta

from ..util import game_from_json, game_to_json, load_json, save_json
from . import espn, odds

log = logging.getLogger(__name__)


def _month_ranges(start, end):
    cur = date(start.year, start.month, 1)
    while cur <= end:
        nxt = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
        yield max(cur, start), min(nxt - timedelta(days=1), end), cur
        cur = nxt


class LiveSources:
    name = "live"

    def __init__(self, cfg, paths, now):
        self.cfg, self.paths, self.now = cfg, paths, now
        self.today = now.date()

    def games(self, seasons=None):
        cur = self.cfg["season"]["current"]
        seasons = seasons or (cur - 1, cur)
        found = {}
        for season in seasons:
            start, end = date(season - 1, 10, 1), date(season, 6, 30)
            end = min(end, self.today + timedelta(days=10))
            for a, b, month in _month_ranges(start, end):
                cache = self.paths.cache / "scoreboard" / f"{month:%Y%m}.json"
                cached = load_json(cache)
                if cached is not None:
                    games = [game_from_json(g) for g in cached]
                else:
                    games = espn.fetch_scoreboard(a, b)
                    # Only cache a month once it is fully in the past and every game is final
                    full_month = (b + timedelta(days=1)).day == 1 or b == date(season, 6, 30)
                    if full_month and b < self.today - timedelta(days=3) and all(g["completed"] for g in games):
                        save_json(cache, [game_to_json(g) for g in games])
                    time.sleep(self.cfg["fetch"]["sleep_seconds"])
                for g in games:
                    found[g["id"]] = g
        return sorted(found.values(), key=lambda g: g["tip"])

    def box_scores(self, games):
        """Box scores for finished current-season games, cached per season."""
        season = self.cfg["season"]["current"]
        path = self.paths.cache / f"box_{season}.json"
        box = load_json(path, {})
        missing = [g["id"] for g in games if g["completed"] and g["season"] == season and g["id"] not in box]
        cap = self.cfg["fetch"]["max_new_boxscores_per_run"]
        errors = 0
        for gid in missing[:cap]:
            try:
                box[gid] = espn.fetch_box(gid)
            except espn.SourceError as e:
                errors += 1
                log.warning("%s", e)
                if errors >= 10:
                    log.warning("Too many box score errors - stopping for this run")
                    break
            time.sleep(self.cfg["fetch"]["sleep_seconds"])
        if missing:
            save_json(path, box, indent=None)
            log.info("Box scores: fetched %d new (%d still missing)", len(missing[:cap]) - errors, max(0, len(missing) - cap))
        return box

    def injuries(self, name_to_abbr):
        return espn.fetch_injuries(name_to_abbr)

    def odds(self):
        oc = self.cfg["odds"]
        return odds.fetch_odds(os.environ.get("ODDS_API_KEY", "").strip(), oc["regions"], oc["markets"])
