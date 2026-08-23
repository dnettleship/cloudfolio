# Pre-session equity & commodities conditions tool — design doc

## Purpose

A tool that runs before a trading session and answers: "what's the state of
the market right now, and which of my watchlist names — or commodities —
look most in play given that state?"

Scope: US equities (mega-cap tech / broad index exposure — e.g. META,
AMZN, MSFT, and Nasdaq-100-tracking positions like EQQQ) alongside two
commodities, oil and gold, where geopolitical drivers are the dominant
signal rather than a supporting one. The watchlist should be configurable,
not hardcoded. Options-specific signals (beyond IV rank as a future
addition) are out of scope for this version.

## Core design principle — read this before building anything

**This tool describes market conditions. It does not predict direction.**

Every component below should output evidence ("VIX at 80th percentile,
breadth narrowing, put/call skewed defensive, FOMC at 2pm") rather than a
verdict ("68% bullish"). Sentiment and breadth data are reasonably good at
characterizing the *regime* — risk-on/risk-off, high/low volatility, broad
vs. narrow participation — but have no reliable track record of predicting
next-session direction. If an implementation detail below would collapse
multiple signals into a single directional number without preserving the
underlying evidence, that's a design smell — stop and keep them separable.

The tool's job is to inform a human decision (or a separate rules-based
system), not to replace one.

**Amendment (2026-08-23):** the written report (see the report-generation
addition under Dashboard + log, below) deliberately breaks this principle in
one place — it ends with a labeled "Likely near-term bias" section giving a
directional call (Bullish/Bearish/Neutral) and a confidence level, on
explicit request. This is a heuristic read with no verified track record,
not a second signal source — it does not feed back into scoring, the
screener, or anything upstream, and it is kept visually and structurally
separate from the evidence sections above it. Every other component in this
document still follows the no-verdict rule as written.

## Architecture overview

```
Market data sources
        |
        v
  Ingestion jobs  <---->  History store
        |                      ^
        v                      |
  Publish gate  ----------------
   |          \
   | pass       \ fail
   v             v
Scoring engine   Keep last-known-good
   |              dashboard, log +
   |              alert, do not
   |              overwrite
   +---------------+
   v               v
Watchlist       Commodities
screener        track (oil, gold)
   |               |
   +-------+-------+
           v
     Dashboard + log
```

Eight components. Watchlist screener and Commodities track run in
parallel off the same scoring engine and history store — equities get a
universe-and-ranking treatment, commodities get a simpler direct read,
since oil and gold are the assets themselves, not a universe to screen.
Each component is described below with its job, inputs/outputs, and the
design constraints that matter.

## Deployment architecture: one Lambda, cleanly modularized

Not a distributed state machine, and not one giant unreadable function
either — a single deployable Lambda, organized into small modules that
map 1:1 onto the 8 components above, so the code structure mirrors the
design doc structure:

```
pre_session_tool/
├── handler.py          # entry point — the whole pipeline in ~8 lines
├── sources/
│   ├── futures_vix.py
│   ├── breadth.py
│   ├── put_call.py
│   ├── calendar.py
│   ├── ig_sentiment.py   # the only module that touches IG secrets
│   ├── gdelt_news.py
│   ├── commodities_price.py
│   └── cot_positioning.py
├── gate.py              # holiday check, required/optional, retry, escalation
├── scoring.py           # percentiles, regime dimensions
├── screener.py
├── commodities.py
├── dashboard.py
└── history_store.py
```

```python
def handler(event, context):
    results = [fetch(src) for src in SOURCES]
    if not gate.publish_ok(results):
        gate.handle_failure(results)
        return
    scores = scoring.compute(results)
    screener_output = screener.rank(scores)
    commodities_output = commodities.evaluate(scores)
    dashboard.publish(scores, screener_output, commodities_output)
```

- Per-connector failure isolation still works exactly as designed — a
  `try/except` around each call in that list comprehension, not a Step
  Functions Map state. With ~8 quick API calls finishing in seconds, well
  inside Lambda's 15-minute timeout, there's no performance need for
  parallel fan-out; if that ever changes, `concurrent.futures` handles it
  inside the same function without introducing an orchestration layer.
- Retry-once-with-backoff is a small helper in `gate.py`, not a
  declarative Retry field on a state machine.
- IG's credentials stay scoped to `ig_sentiment.py` — the only module
  that fetches them from Secrets Manager — without needing a separate
  IAM role to enforce that boundary.
- One deployment package, one log group, one place to look when
  something breaks.

## 1. Market data sources

Per-source candidates to evaluate (pick based on cost/free-tier limits at
build time — this list is a starting point, not a commitment):

- **Futures / index prices, VIX**: `yfinance` — free. `ES=F` / `NQ=F` for
  S&P 500 / Nasdaq-100 futures, `^VIX` for spot volatility.
- **Breadth** (advance/decline, new highs/lows, % above moving averages):
  computed in-house from S&P 500 constituent daily OHLCV, pulled via
  `yfinance` in one batch call (`yf.download(tickers=[...], period="1y",
  group_by="ticker", threads=True)`). A year of daily history for ~500
  tickers comes back in one pass, which seeds the history store's
  percentile baseline immediately rather than waiting months to
  accumulate it. Advance/decline, new-highs/lows, and % above a moving
  average are then just pandas operations on that dataframe. The
  constituent list itself isn't in `yfinance` — source it from a Wikipedia
  table scrape (`pandas.read_html`) or a maintained community CSV, and
  refresh it periodically since index membership changes.
- **Options positioning**: CBOE daily put/call ratio data (equity-only and
  total). Delayed by end-of-day, not intraday. Not available via
  `yfinance` — pull directly from CBOE's published data.
- **Economic calendar**: two distinct sources, not one. General macro data
  (CPI, NFP, PMI, retail sales) from Finnhub's economic calendar endpoint
  or Trading Economics — high frequency, needs live polling. Central bank
  decision days (FOMC primarily, optionally ECB/BoE for cross-market
  context) are better tracked as a small maintained reference list
  refreshed a few times a year from the central banks' own published
  calendars — federalreserve.gov publishes FOMC dates 1–2 years out (8
  meetings/year, decisions at 2:00pm ET) and the schedule essentially
  never moves once published, so a live API dependency is more fragile
  than a short static table for this specific category. Not available
  via `yfinance` either way.
- **US market holiday calendar**: another small, low-maintenance static
  list, same treatment as FOMC dates — NYSE publishes its holiday
  schedule well in advance. This isn't a data *source* so much as a
  precondition check — see the publish gate below.
- **Sector performance**: daily returns on the standard sector ETFs
  (XLK, XLF, XLE, etc.) — same `yfinance` batch call as the constituents.
- **Cross-asset**: `yfinance` again — `^TNX` for the 10-year yield,
  `DX-Y.NYB` (or the `UUP` ETF as a proxy) for the dollar. Doubles as a
  primary driver read for gold (which moves inversely with real yields
  and the dollar), not just equity context.
- **Retail positioning**: IG's client sentiment endpoint
  (`/clientsentiment/{marketId}`) — directly relevant since this is the
  broker actually used for spread betting. Query it for the gold and oil
  marketIds too, not just equity indices — same connector, more instruments.
- **Geopolitical / macro news**: GDELT's Doc API (free, no key, updated
  every 15 minutes) via the `gdeltdoc` Python client, queried against a
  curated set of market-relevant keywords. For equities: sanctions,
  tariffs, chip export controls. For oil and gold specifically, extend the
  keyword set: OPEC, OPEC+, Strait of Hormuz, pipeline disruption, Russia
  sanctions, safe-haven flows, central bank gold buying — this is a
  first-class signal for commodities, not just supporting context, given
  how directly geopolitics moves these two.
- **Oil and gold prices**: `yfinance` — `CL=F` (WTI) and/or `BZ=F` (Brent)
  for oil, `GC=F` for gold. Same batch-download pattern as the equity
  universe.
- **Commodities positioning**: the CFTC's weekly Commitment of Traders
  report — free, and both gold (COMEX) and WTI crude (NYMEX) are among the
  most liquid, well-covered contracts it publishes, unlike thinner
  commodities. The `cot_reports` Python package wraps CFTC's published
  data cleanly. Published Fridays, reflecting the prior Tuesday's
  positions — a 3-day-old read by design, same staleness-labeling
  discipline as the equities' COT-style data applies here.

## 2. Ingestion jobs

- One codebase, not two tools. Scheduling differences (a UK-morning glance
  vs. the pre-open run) are handled by triggering the same pipeline on
  multiple schedules, tagging each stored snapshot with its run type — not
  by maintaining separate copies of the ingestion/scoring logic.
- Both the UK-morning and pre-US-open runs are genuinely decision-relevant
  — US index exposure (IG's futures-priced US 500 / US Tech 100 / Wall
  Street spread bets, and LSE-listed ETFs like EQQQ) is tradeable well
  before the US cash market opens, so a UK-morning run isn't just an
  informational glance. The one caveat: individual US shares are
  generally only quotable while the underlying US exchange is open, so
  the watchlist screener's single-ticker rankings are mainly actionable
  at the pre-open run — the UK-morning run is most useful for the regime
  read itself and for index/ETF-level decisions. Either way, a run
  anchored well before 8:30am ET will still miss that morning's economic
  data print if one lands close to the US open.
- Gold and oil are effectively 24-hour markets on IG (spot gold and oil
  trade close to continuously, Sunday 11pm to Friday 10pm UK time; futures
  versions run nearly 24/5 too), so unlike equities they don't have a
  single "open" to anchor around — both scheduled runs are equally valid
  checkpoints for the commodities track. Two commodity-specific timing
  quirks worth flagging on the dashboard: the weekly EIA petroleum status
  report (Wednesdays, 3:30pm UK time — a predictable, published-in-advance
  schedule much like FOMC, so track it the same low-maintenance way rather
  than depending on a general calendar feed to catch it) and OPEC+ meeting
  days, which are announced ahead of time but on a less rigid cadence than
  FOMC.
- EventBridge Scheduler (not the legacy EventBridge Rules, which are
  UTC-only) triggers the Lambda directly. Set `ScheduleExpressionTimezone`
  to `America/New_York` so the schedule stays pinned to local market
  time — e.g. `cron(45 8 ? * MON-FRI *)` for 8:45am ET — and adjusts
  automatically across DST, without the UK/US clock-change mismatch
  causing an hour of drift twice a year.
- One connector per source, each its own small module under `sources/`
  (see Deployment architecture above), called in a simple loop within the
  Lambda. Each returns a result object — `{source, value, timestamp,
  status: success|failed}` — rather than raising and killing the whole
  ingestion run. A dead calendar API should not prevent the VIX connector
  from completing.
- Idempotent: re-running a job for a date that already has data overwrites
  cleanly rather than duplicating.

## 3. Publish gate (data validation)

This is what "the report cannot be published without successful data
calls" means in practice — a checkpoint between ingestion and everything
downstream, not just a hope that nothing failed.

- Classify each source as **required** or **optional** for publish. A
  reasonable starting split: futures/VIX, breadth, and oil/gold prices are
  required (the volatility, breadth, and commodities dimensions depend on
  them directly); put/call, calendar, IG sentiment, GDELT news, and COT
  positioning are optional (their dimensions or panels can render as "no
  data" without invalidating the rest of the report). This split is a
  config list, not a hardcoded rule — tune it as the tool matures.
- Check the US market holiday calendar before treating "no new data" as a
  failure. On a holiday, breadth and futures genuinely won't move — that's
  an expected quiet day, not a broken source. The gate should skip the
  retry/escalation path entirely and the dashboard should read "market
  closed today" rather than implying a data problem.
- After ingestion finishes, check the result objects: if every **required**
  source has `status: success`, proceed to scoring. If any required source
  failed, retry once with a short backoff (catches transient blips), then
  re-check.
- If a required source is still failing after the retry: **do not run
  scoring or overwrite the dashboard.** Leave the last successfully
  published snapshot in place — clearly timestamped, so it reads as
  "yesterday's read" rather than silently pretending to be current — log
  which source(s) failed and why, and send a notification (even just a
  local one).
- Track consecutive gate failures per source (a small counter in the
  history store). A single failed run stays a routine log line, matching
  the rest of this section — but if the same source is still failing
  after N consecutive runs (e.g. 3), escalate from a routine log to
  something that actually gets noticed (push/email rather than a local
  notification). This is what catches a source that's been silently
  broken for days, like an unannounced `yfinance` breakage, rather than
  a one-off blip.
- This is the same gate pattern as a blue/green deployment health check —
  don't cut over to new state unless the preconditions for it actually
  held. The next scheduled run is the natural retry; no separate recovery
  path is needed.
- Optional sources that failed still get logged and still show as
  "no data" on the dashboard rather than being silently omitted — the
  distinction from required sources is only whether their failure blocks
  publish.

## 4. History store

- Stores daily snapshots: raw inputs plus computed scores, one row (or
  document) per instrument per day.
- Needs roughly a year of trailing history per signal at minimum, since
  the scoring engine's percentiles are computed against a signal's own
  recent range, not fixed thresholds.
- Doubles as the audit trail — this is what lets you check, months later,
  whether the tool's reads meant anything, and what lets you backtest
  changes to the scoring logic without losing comparability to prior runs.
- Any change to how a score is computed should be versioned (a scoring
  logic version tag stored alongside each day's row), so a backtest run
  against old data doesn't silently mix two different scoring definitions.
- Only snapshots that passed the publish gate get written as the
  "current" record — a failed/gated run should not corrupt the history
  used for percentile calculations.

## 5. Scoring engine

- Converts each raw input to percentiles against its own trailing
  history — computed against **two windows, not one**: a short one
  (~60 days) and a long one (~1 year), both shown rather than collapsed
  into a single figure. A single long window can quietly hide a genuine
  regime shift (e.g. "VIX at the 80th percentile of the last 12 months"
  reads very differently depending on whether the last year was
  unusually calm or unusually volatile) — showing both keeps "elevated
  vs. recently" and "elevated vs. the long run" visibly separate.
- Also surfaces trend, not just level: the percentile now alongside the
  percentile a few sessions ago (e.g. "breadth: 30th percentile, down
  from 65th two sessions ago"). This is a fact already sitting in the
  history store, not a new prediction — whether a reading is the first
  day of a shift or the fifth day changes what it means.
- Groups percentiles into a small number of named dimensions rather than
  one blended score:
  - **Volatility** (VIX level/change, IV-based measures)
  - **Breadth / participation** (advance/decline, new highs vs lows, %
    above moving averages)
  - **Positioning** (put/call ratio, IG retail sentiment)
  - **Macro event risk** (today's calendar — CPI/NFP/PMI, plus a distinct,
    always-high flag on any scheduled FOMC/central-bank decision day,
    since those are the largest scheduled risk events by category, not
    just another data point in the mix)
- Does not combine these four into a single directional number. Keeping
  them separate is what keeps the output auditable and honest — see the
  design principle above.
- Geopolitical/macro news (GDELT) does **not** become a 5th dimension —
  it's a curated list of flagged headlines, not a score. The most useful
  treatment is cross-referencing headline timing against the volatility
  dimension: when VIX/futures show an unusual overnight move, surface
  whichever flagged headlines line up with that timing as likely
  context — explaining a move the numeric data already caught, rather
  than a text model trying to predict on its own. For oil and gold, this
  same GDELT feed is weighted as a first-class input in the commodities
  track below, not just explanatory context.

## 6. Watchlist screener

- Universe: Nasdaq-100 constituents (the index EQQQ tracks) rather than a
  strict GICS "Technology" sector filter — GICS classifies META/GOOGL as
  Communication Services and AMZN as Consumer Discretionary, which would
  exclude names that obviously belong in a "US tech" watchlist.
- Default selection criteria within that universe: high liquidity (average
  daily dollar volume over a trailing 20–60 day window, above a floor like
  $500M–$1B) and high beta vs SPY/QQQ (rolling beta over 60–252 days,
  above ~1.2–1.3). Both are computed from the same constituent OHLCV
  already pulled for breadth — no separate data source needed.
- Actual holdings (META, AMZN, MSFT, EQQQ's constituents) are always
  included in the screener's output regardless of whether they clear the
  liquidity/beta filter — MSFT in particular won't always meet a 1.2+
  beta threshold, and a filter tuned to find new high-beta opportunities
  shouldn't silently drop the positions already held. The filter's job is
  to surface additional candidates beyond the holdings, not to gate them.
- MVP: seed with a static list first
  (e.g. `NVDA, TSLA, AMD, META, AMZN, MSFT, AAPL, GOOGL, AVGO, NFLX, CRM,
  MRVL, CRWD, PANW, MU, ARM, PLTR`) and replace it with the dynamic
  liquidity/beta filter once the constituent pipeline is in place —
  membership and beta drift over time, so the static list is a starting
  point, not the long-term source of truth.
- For each ticker: overnight gap %, relative strength vs SPY/QQQ over the
  last few sessions, IV rank if available.
- Cross-references these against the day's regime dimensions and calendar
  to rank/highlight which names look most "in play" that session.
- Output is a ranking, not a recommendation — no buy/sell/size suggestion.

## 7. Commodities track (oil, gold)

Runs alongside the watchlist screener, not through it — oil and gold
aren't a universe to rank, they're the two assets themselves, so the
treatment is simpler and more direct than the equity screener.

- For each of oil and gold, compute against trailing history (both the
  60-day and 1-year windows, same as the equity dimensions): price
  percentile within its recent range, and realized volatility percentile
  (there's no free options-implied-volatility source for these the way
  VIX exists for equities, so historical/realized volatility from the
  same `yfinance` price series is the pragmatic substitute).
- COT positioning percentile: managed-money net position vs. its own
  trailing range — the classic commodities positioning signal flagged
  early in this design (extreme positioning has historically coincided
  with turning points in metals and energy). Same 3-day-lag caveat as
  the rest of the COT data.
- GDELT-flagged headlines specific to each commodity's keyword set (see
  above) are a first-class panel here, not side context — surfaced
  directly, evidence-first, same as everywhere else in this design, never
  collapsed into a fabricated directional score.
- The EIA-Wednesday and OPEC+-meeting-day flags apply specifically to
  oil; gold's dimension leans more on the cross-asset (USD/real yield)
  reading than a scheduled-event flag, since gold doesn't have an
  equivalent weekly data release.
- Output stays in the same evidence-based, non-predictive shape as
  everything else: "gold: price at 85th percentile, COT net-long at a
  2-year extreme, USD weakening, no scheduled events" — not a buy/sell
  call.

## 8. Dashboard + log

- Feeds a tile suitable for a tablet display: the four equity regime
  dimensions with their supporting evidence (level and recent trend),
  today's calendar highlights — with central bank decision days shown
  explicitly by name and time (e.g. "FOMC decision, 2:00pm ET") rather
  than folded anonymously into a score — any flagged geopolitical/macro
  headlines from GDELT, the screener's top few names (holdings always
  included), and the oil/gold commodities track's readings.
- Only updates when the publish gate passes. On a gated/failed run, the
  tile keeps showing the last successful snapshot with its original
  timestamp, rather than a blank or partially-overwritten state. On a
  market holiday, it reads "market closed today" rather than either of
  those.
- Writes the same snapshot back to the history store.
- **Output must be easy to read, concise, and favor charts over prose
  wherever possible** — this is a tablet dashboard meant for a glance, not
  a report to sit and read. The way to reconcile this with the
  evidence-first principle above (show evidence, not just a verdict) is
  visual compression, not omission: a small percentile gauge and a
  sparkline of the trend convey "80th percentile, up from 45th two
  sessions ago" in one glance, faster and more legibly than the
  equivalent sentence. Reserve prose/text for what's inherently
  textual — calendar event names and times, headline snippets, ticker
  symbols — rather than forcing those into a chart where it wouldn't
  help.

### Written report (implemented, ahead of the phases below)

Built earlier than the phase plan called for, once the Phase 1 dashboard
proved the gauges/numbers alone weren't a useful read on their own. On a
successful scan, the Lambda sends the full result dict to Claude (Haiku 4.5)
with a prompt asking for a short prose report in three parts: 3-4 paragraphs
of evidence covering the overall market backdrop, not just the watchlist
(mirroring the dashboard's dimensions, plus 1-2 relevant news headlines when
present); a short "Upcoming events" note on near-term watchlist earnings and
the next FOMC meeting (from the `calendar` field — see Ingestion jobs
above); then a labeled "Likely near-term bias" section for the *broader
market*, not narrowly the watchlist — see the Amendment under Core design
principle above for why that last part is scoped as an explicit, isolated
exception to the no-verdict rule rather than a new signal. Failure is
non-fatal: if the API call errors (bad/missing key, rate limit, etc.), the
scan still returns successfully with `report_error` set instead of `report`,
and the gauges/table still render — matching the "keep last-known-good,
don't let one failing part take down the rest" spirit of the publish gate,
even though this specific call sits downstream of that gate rather than
inside it.

Every successful scan (report included) is also written to a private S3
bucket, one JSON object per run — the web-side realization of the History
store component (#4) above, ahead of that component's own listed build
order too. A second Cloudfolio site tab ("Archive") lists and re-renders
past reports from it. Unlike the local CLI's `history/` directory, this
bucket has no `force_destroy` — a `terraform destroy` of this stack (no CI
destroy workflow exists for it yet, unlike cloudfolio's) will refuse to
remove it while it holds objects, rather than silently wiping accumulated
report history.

## Engineering considerations

- Treat data freshness as an SLO — the dashboard should visibly flag any
  field that's stale relative to what's normal for that source.
- Monitor the pipeline itself, not just the market: alert (even just a
  local notification) if a source has failed silently rather than letting
  the dashboard show yesterday's number as if it were current. Structured
  logging — one JSON line per source result (source, status, timestamp)
  from within the single Lambda — gives the same debugging visibility via
  CloudWatch Logs Insights, useful both for day-to-day debugging and for
  the escalation counter in the publish gate, without a separate
  orchestration layer to get it.
- Backtest changes to the scoring logic the way you'd validate a code
  change — check for look-ahead bias (was this data actually available at
  that timestamp historically?) before trusting a backtest result.
- `yfinance` is an unofficial wrapper around Yahoo's endpoints, not a
  published stable API — it can break or get rate-limited without notice.
  Batch requests, cache what's already fetched, and let it fail into a
  flagged-stale state rather than taking the whole run down.
- **Secrets**: IG API credentials and any third-party API keys go in AWS
  Secrets Manager or SSM Parameter Store — never hardcoded or committed
  alongside the Lambda code. Keep that access scoped to `ig_sentiment.py`
  (see Deployment architecture) rather than pulling every secret into
  shared global state at startup — a code-level boundary, not a separate
  IAM role, but the same principle: only the code that needs a credential
  touches it.
- **Cost ceiling**: a basic AWS Budgets alarm at a low threshold, so an
  unattended twice-daily job that quietly starts costing more (a batch
  call that loops, retries that fire too aggressively after some change)
  gets caught early rather than showing up as a surprise bill months in.

## Build phases

- **Phase 1 — MVP**: `yfinance`-only data (futures/VIX, constituent OHLCV
  for breadth, and oil/gold prices with realized-volatility percentiles —
  all free, same batch pattern, no new infrastructure). Scoring covers
  volatility + breadth/participation for equities, plus the basic
  price/volatility read for oil and gold. Screener runs against the
  static seed list with gap % and relative strength (no IV rank yet).
  History store live from day one, seeded via the bulk backfill. Publish
  gate is trivial here — futures/VIX, breadth, and oil/gold prices are
  the only sources, and all are already required. Schedule: both the
  UK-morning and pre-open runs from day one, tagged by run type — all
  genuinely tradeable sessions given IG's futures-priced index products,
  ETF access, and the near-24-hour gold/oil markets. Dashboard output can
  be minimal (even a plain page) — the goal is an end-to-end working
  pipeline before adding harder integrations.
- **Phase 2 — full scoring**: add CBOE put/call, the economic calendar,
  IG client sentiment, GDELT geopolitical news, and CFTC COT positioning
  for oil and gold. Unlocks the positioning and macro-event-risk
  dimensions for equities, and the positioning/geopolitical panels for
  the commodities track. These all become *optional* sources in the
  publish gate, as already specced.
- **Phase 3 — screener maturity**: replace the static equity watchlist
  with the dynamic Nasdaq-100 liquidity/beta filter.
- **Phase 4 — hardening**: IV rank (once an options data source is
  chosen), tablet-specific dashboard styling (gauges/sparklines per the
  readability requirement above — the Phase 1–3 plain-page output is
  fine for proving the pipeline, but shouldn't be mistaken for the
  final target), a proper alerting channel, and a backtesting harness
  for validating scoring-logic changes before they go live.
