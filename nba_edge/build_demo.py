"""Build dist/demo.html: the whole site in one file, filled with demo data.

  python -m nba_edge.build_demo
Open dist/demo.html in any browser to preview the site without keys or GitHub.
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

from .backtest import run_backtest
from .pipeline import run
from .sources.demo import DemoSources
from .util import ROOT, load_config, utcnow


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        shutil.copy(ROOT / "config.yaml", tmp / "config.yaml")
        run(mode="manual", root=tmp, demo=True)
        today = (tmp / "site/data/today.json").read_text(encoding="utf-8")
        results = json.loads((tmp / "site/data/results.json").read_text(encoding="utf-8"))
    cfg = load_config()
    results["backtest"] = run_backtest(cfg, DemoSources(cfg, utcnow()).games(), {cfg["season"]["current"] - 1})
    results = json.dumps(results)
    site = ROOT / "site"
    html = (site / "index.html").read_text(encoding="utf-8")
    css = (site / "styles.css").read_text(encoding="utf-8")
    js = (site / "app.js").read_text(encoding="utf-8")
    data = f"window.__TODAY__={json.dumps(json.loads(today))};window.__RESULTS__={json.dumps(json.loads(results))};"
    html = html.replace('<link rel="stylesheet" href="styles.css">', f"<style>{css}</style>")
    html = html.replace('<script src="app.js"></script>', f"<script>{data}</script><script>{js}</script>")
    out = ROOT / "dist" / "demo.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
