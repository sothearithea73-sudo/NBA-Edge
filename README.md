# NBA Edge

A website that updates itself every day with NBA projections for every game
on the schedule. For each game it compares the model's numbers with live
bookmaker odds and shows where (if anywhere) the model disagrees enough to
be worth a bet.

**Read this first.** No model can guarantee wins. NBA betting lines are very
sharp, and most models, including well-built ones, lose to the bookmaker's
margin. This site is built to be honest about that: it defaults to *Pass*,
blends its view with the market's, caps stakes, and tracks closing line value
(CLV) so you can tell whether it has a real edge **before** you risk real money.
Paper-trade it for at least a few weeks first.

---

## What you get

| | |
|---|---|
| **Today page** | One card per game: win probability, projected margin and total with an 80% range, the market's no-vig probabilities, edge, EV, verdict (Value bet / Lean / Pass / No pick), suggested stake for your bankroll, injuries with point impact, projected starters, rest/travel/altitude factors, line movement |
| **Results page** | Every Value bet the site has flagged, graded automatically: record, units, ROI, average CLV, % of bets that beat the closing line, plus your backtest results |
| **Automation** | GitHub Actions runs a full update every morning (6:00am Brisbane) and again ~1 hour before each tip-off window, then publishes to GitHub Pages |
| **Safety rails** | No picks when the injury report or odds are missing or stale, one bet per game, quarter-Kelly stakes capped at 2% per bet and 8% per day |

## How the model works (short version)

1. **Team ratings** from every finished game's score, adjusted for opponent and
   home court, with recent games weighted more and last season fading out.
2. **Situational adjustments:** back-to-backs, 3 games in 4 nights, rest
   difference, travel distance and time-zone changes on short rest, altitude
   (Denver/Utah), neutral sites.
3. **Injuries:** each player's on/off plus-minus this season, shrunk for small
   samples. A team only moves when tonight's availability differs from how often
   the player has played lately, so long-term absences aren't double counted.
4. **Probabilities:** projected margin/total converted with a bell curve
   (`margin_sd`, `total_sd`, re-fit by the backtest).
5. **Versus the market:** bookmaker prices with the margin removed, consensus
   (median) across books, best available price for EV. The model is blended
   60/40 with the market before measuring edge.

Every weight is in **`config.yaml`**, with a comment explaining it.

## Data sources and costs

| Source | Used for | Cost / limits |
|---|---|---|
| ESPN public JSON (`site.api.espn.com`) | Schedule, scores, box scores (minutes, plus-minus), injury report | Free, no key. **Unofficial**: ESPN can change it without notice. The code fails with a clear message if it does |
| [The Odds API](https://the-odds-api.com) | Moneyline, spread and total prices from Australian bookmakers | Free plan: 500 credits/month. Each call costs 3 credits (3 markets x 1 region). With the 4-calls-a-day cap that is at most ~360/month. Adding the `us` region doubles it |
| GitHub Actions | Runs the updates | Free and unlimited on a public repo. Private repos get 2,000 free minutes/month; this uses roughly 1,000-1,200 (the quick 30-minute checks add up) |
| GitHub Pages | Hosts the site | Free (the free plan requires a public repo) |

Not used, on purpose: `stats.nba.com` (often blocks requests from cloud
servers like GitHub's) and the NBA's official injury-report PDFs (fragile to
parse). ESPN's injury feed carries the same statuses.

---

## Setup guide (no GitHub experience needed)

### 1. Create a GitHub account and a repository
1. Go to [github.com](https://github.com) and sign up (free).
2. Top-right **+** → **New repository**.
3. Name it e.g. `nba-edge`, choose **Public** (needed for free Pages hosting),
   leave everything else unticked, click **Create repository**.

> Public means anyone with the link can see your picks and code. Your API key
> stays private either way, because it lives in Secrets (step 3).

### 2. Upload the project files

**Option A: in the browser (easiest)**
1. Unzip `nba-edge.zip` on your computer.
2. On your new repo page click **uploading an existing file**.
3. Open the unzipped `nba-edge` folder, select **everything inside it**, and drag it
   into the page. Check the `.github` folder came across: it's hidden on some
   computers. On a Mac press `Cmd + Shift + .` in Finder to show hidden files;
   on Windows, View → Show → Hidden items.
4. Click **Commit changes**.
5. Check the repo now shows `.github/workflows/daily-update.yml`. If it doesn't, click
   **Add file → Create new file**, type `.github/workflows/daily-update.yml` as
   the name, paste in that file's contents, and commit.

**Option B: with git (if you have it installed)**
```bash
cd nba-edge
git init
git add .
git commit -m "First version"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/nba-edge.git
git push -u origin main
```

### 3. Get your odds API key and store it as a Secret
1. Sign up at [the-odds-api.com](https://the-odds-api.com) (free plan). The key is emailed to you.
2. In your repo: **Settings → Secrets and variables → Actions → New repository secret**.
3. Name: `ODDS_API_KEY`. Secret: paste the key. **Add secret**.

Never paste the key into any file in the repo.

### 4. Turn on GitHub Pages
1. **Settings → Pages**.
2. Under **Build and deployment → Source**, choose **GitHub Actions**.
3. Your site's address will be `https://YOUR-USERNAME.github.io/nba-edge/`
   (it's also shown here after the first successful run).

### 5. Allow the workflow to save data
**Settings → Actions → General → Workflow permissions** → choose
**Read and write permissions** → **Save**.

### 6. Run it for the first time
1. Click the **Actions** tab. If asked, click **I understand my workflows, go ahead and enable them**.
2. Click **Daily NBA update** on the left → **Run workflow** → **Run workflow**.
3. Wait 3-8 minutes. The first run takes longest, because it downloads every box score
   so far this season. A green tick means it worked; open your site link.

From now on it runs by itself. Click **Run workflow** any time big injury news
breaks and you want fresh numbers.

### 7. Reading the logs and fixing common errors
Click any run in the **Actions** tab, then the **update** job, then a step to
see its log. Warnings (yellow) and errors (red) also appear on the run's summary page.

| You see | What it means / fix |
|---|---|
| `ODDS_API_KEY is not set` | Step 3 wasn't done, or the secret name is misspelled (it must be exactly `ODDS_API_KEY`) |
| `Odds API rejected the key (HTTP 401)` | Key copied wrong. Re-create the secret |
| `Odds API quota used up (HTTP 429)` | Monthly credits are gone. Lower `odds.max_calls_per_day` in `config.yaml` or wait for the reset |
| `Permission denied` / `403` when pushing | Step 5 wasn't done |
| Deploy step fails with `Pages not enabled` | Step 4 wasn't done (Source must be **GitHub Actions**) |
| `...espn.com... failed after 3 tries` | ESPN was down or blocked the request. Usually fixes itself next run; the site shows a warning instead of picks |
| `box score ...: expected 2 teams` | ESPN changed its format. Injury adjustments switch off until fixed; open an issue or ask Claude to update `nba_edge/sources/espn.py` with an example of the new response |
| Most runs show **gate** only and skip **update** | Normal. The 30-minute checks only update when a tip-off is about an hour away |
| Scheduled runs stopped | GitHub pauses schedules in repos with no activity for 60 days. The data commits normally count as activity; if it pauses, click **Enable workflow** in the Actions tab |

### 8. Changing settings later
- **Model or betting rules:** edit `config.yaml` on GitHub (click the file → pencil
  icon → **Commit changes**). The next run uses the new values.
- **Run times:** edit the `cron:` lines in `.github/workflows/daily-update.yml`.
  Times are **UTC**; Brisbane = UTC + 10. If you change the first (morning) line,
  change `schedule.morning_cron` in `config.yaml` to match exactly.
- **New season:** each October, bump `season.current` in `config.yaml` (e.g. 2027 → 2028).

---

## Running it on your own computer (optional)
```bash
python -m pip install -r requirements.txt
python -m pytest -q                         # tests, all offline
python -m nba_edge.build_demo               # dist/demo.html: site preview with invented data
ODDS_API_KEY=yourkey python -m nba_edge.run # real update, writes site/data/*.json
python -m http.server -d site 8000          # then open http://localhost:8000
```

## Backtesting
```bash
python -m nba_edge.backtest --seasons 2025 2026
```
Rates teams using only earlier games, predicts every game of those seasons and
reports log loss, Brier score, calibration and margin/total error. It also
prints the best-fitting `margin_sd` and `total_sd`: copy those into `config.yaml`.
Commit `data/backtest.json` and the Results page will show it.

To test **ROI against closing lines** you need historical odds (The Odds API's
historical data is a paid add-on; free CSVs exist online). Format, decimal prices:
```
date,home,away,home_ml,away_ml,home_spread,home_spread_price,away_spread_price,total,over_price,under_price
2026-01-15,BOS,NY,1.62,2.40,-4.5,1.91,1.91,224.5,1.91,1.91
```
```bash
python -m nba_edge.backtest --seasons 2026 --odds-csv closing_odds.csv
```
The key line in the output compares **model log loss vs market log loss**. If
the market's is lower (it usually is), the market predicts better than the model.

**Not backtested:** the injury layer, because free historical injury reports
don't exist. Judge it by live CLV on the Results page.

## Project layout
```
config.yaml                     all weights and rules
nba_edge/
  run.py                        one full update  (python -m nba_edge.run)
  gate.py                       "should this scheduled run update now?"
  pipeline.py                   fetch → model → markets → history → site JSON
  ratings.py                    opponent-adjusted team ratings
  players.py                    on/off impact, injury adjustment, projected starters
  situational.py                rest, back-to-backs, travel, time zones, altitude
  model.py                      projections and team stats
  markets.py                    no-vig, edge, EV, Kelly, verdicts, exposure cap
  history.py                    pick log, grading, CLV
  backtest.py                   walk-forward backtest
  build_demo.py                 one-file preview with invented data
  sources/espn.py, odds.py      data feeds;  live.py caching;  demo.py invented data
site/                           the website (index.html, app.js, styles.css, data/)
data/                           cache, pick history, state (committed by the workflow)
.github/workflows/daily-update.yml
tests/
```

## Known limits
- Projected starters come from each team's last game plus the injury report.
  Confirmed lineups come out ~30 minutes before tip, after the last update.
- Late scratches after the pre-tip run aren't seen. Always check news before betting.
- Plus-minus is noisy, especially early in the season. The shrinkage makes
  injury adjustments cautious until players have a few hundred minutes.
- Spread/total books at different lines are compared at the most common line only.

## Gamble responsibly
Set a bankroll you can afford to lose completely and never top it up to chase
losses. If betting stops being fun, talk to someone:
**Gambling Help Online, 1800 858 858** (free, 24/7, Australia),
[gamblinghelponline.org.au](https://www.gamblinghelponline.org.au).
