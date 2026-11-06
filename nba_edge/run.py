"""Run one update.

  python -m nba_edge.run                 # full update with live data (needs ODDS_API_KEY)
  python -m nba_edge.run --mode pretip   # same, marks the pre-tip refresh as done
  python -m nba_edge.run --demo          # invented data, to preview the site offline
"""
import argparse
import logging
import sys

from .pipeline import run


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="manual", choices=["morning", "pretip", "manual", "skip"])
    ap.add_argument("--demo", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    return run(mode=args.mode, demo=args.demo)


if __name__ == "__main__":
    sys.exit(main())
