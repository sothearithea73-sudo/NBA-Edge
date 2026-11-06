"""Small shared helpers: paths, JSON files, names, dates, maths."""
import json
import os
import re
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import NormalDist

import yaml

ROOT = Path(__file__).resolve().parent.parent
NORMAL = NormalDist()


class Paths:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.config = self.root / "config.yaml"
        self.data = self.root / "data"
        self.cache = self.data / "cache"
        self.state = self.data / "state.json"
        self.history = self.data / "history" / "picks.json"
        self.backtest = self.data / "backtest.json"
        self.site_data = self.root / "site" / "data"


def load_config(path=None):
    with open(path or ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _default(o):
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    raise TypeError(f"not JSON serialisable: {type(o)}")


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, obj, indent=1):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, default=_default, indent=indent, ensure_ascii=False)
    os.replace(tmp, path)


def norm_name(s):
    s = (s or "").lower().replace("la clippers", "los angeles clippers")
    s = re.sub(r"[^a-z0-9 ]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def season_of(d):
    """ESPN season label: games from Aug onwards belong to next year's season."""
    return d.year + 1 if d.month >= 8 else d.year


def utcnow():
    return datetime.now(timezone.utc)


def parse_dt(s):
    dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def game_to_json(g):
    out = dict(g)
    out["tip"] = g["tip"].isoformat()
    out["et_date"] = g["et_date"].isoformat()
    return out


def game_from_json(d):
    g = dict(d)
    g["tip"] = parse_dt(d["tip"])
    g["et_date"] = date.fromisoformat(d["et_date"])
    return g
