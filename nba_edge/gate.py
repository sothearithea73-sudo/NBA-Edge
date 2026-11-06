"""Decides whether a scheduled run should do a full update.

The workflow wakes up every 30 minutes during US game hours. This check is
quick (no odds credits used): it only says "go" for the morning run, manual
runs, or when a tip-off is ~35-95 minutes away and hasn't had its refresh yet.

Usage: python -m nba_edge.gate --event schedule --schedule "0 20 * * *"
"""
import argparse
import logging
import os
import sys

from .pipeline import pick_slate
from .sources.live import LiveSources
from .util import Paths, load_config, load_json, utcnow


def decide(event, schedule, now, games, state, cfg):
    if event != "schedule":
        return True, "manual", "manual run"
    if schedule.strip() == cfg["schedule"]["morning_cron"]:
        return True, "morning", "morning run"
    lo, hi = cfg["schedule"]["pretip_window_minutes"]
    done = set(state.get("pretip_done", []))
    _, slate = pick_slate(games, now)
    for tip in sorted({g["tip"] for g in slate if g["state"] == "pre"}):
        mins = (tip - now).total_seconds() / 60
        if lo <= mins <= hi and tip.isoformat() not in done:
            return True, "pretip", f"tip-off in {mins:.0f} min"
    return False, "skip", "no tip-off in the pre-game window"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--event", default="workflow_dispatch")
    ap.add_argument("--schedule", default="")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    paths = Paths()
    cfg = load_config(paths.config)
    now = utcnow()
    state = load_json(paths.state, {}) or {}
    games = [] if args.event != "schedule" or args.schedule.strip() == cfg["schedule"]["morning_cron"] \
        else LiveSources(cfg, paths, now).games(seasons=(cfg["season"]["current"],))
    go, mode, why = decide(args.event, args.schedule, now, games, state, cfg)
    print(f"Gate: {'RUN' if go else 'SKIP'} ({why})")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"run={'true' if go else 'false'}\nmode={mode}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
