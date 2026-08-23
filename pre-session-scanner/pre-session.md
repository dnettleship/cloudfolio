# Pre-session scanner — summary

A tool that runs before a trading session and answers: what's the state of
the market right now, and which watchlist names or commodities (oil, gold)
look most in play given that state?

It describes conditions — it does not predict direction. Every output is
evidence (VIX percentile, breadth trend, today's calendar) shown separately,
never blended into a single directional score. The goal is to inform a
human decision, not replace one. One explicit, isolated exception: the
written report (below) ends with a labeled, on-request "likely near-term
bias" call — see the Amendment in the design doc for why that's scoped as
a deliberate carve-out rather than a quiet reversal of the principle.

**Shape**: scheduled ingestion from ~8 market data sources → a publish gate
that blocks the dashboard from updating if required data is missing →
percentile-based scoring across a few named dimensions (volatility, breadth,
positioning, macro event risk) → a watchlist ranking and a separate oil/gold
read → a tablet-friendly dashboard, chart-first.

**Deployment**: one Lambda, modularized to mirror the design's components —
not a distributed system.

**Build order**: MVP on free `yfinance` data only (volatility + breadth +
commodity prices) → add paid/richer sources (put/call, calendar, IG
sentiment, GDELT news, COT positioning) → mature the watchlist from a static
list to a dynamic liquidity/beta filter → harden (IV rank, dashboard
styling, alerting, backtesting).

## Current status (Phase 1 MVP)

- `scanner.py` — local CLI, `yfinance`-only data. Prints JSON, writes a daily
  history snapshot and a plain-page `dashboard.html`, both gitignored.
- Also deployed as an on-demand Lambda (`infra/pre-session-scanner/`,
  `POST /scan`), reusing the exact same `scanner.py`/`dashboard.py` — no
  separate web reimplementation. No scheduling yet — every run, local or
  web, is on-demand.
- `report.py` turns a scan's data into a short written report via Claude
  (Haiku 4.5) — the Lambda calls it after every successful scan; the CLI
  does not (JSON/dashboard.html only, no API key wired up locally yet).
- On the Cloudfolio site (`infra/cloudfolio/frontend/index.html`): a
  **Pre-session Scanner** tab (the "Run scan" button, live report + gauges +
  screener) and an **Archive** tab (`GET /archive`, lists every past scan
  saved to S3, click to expand its report). Nav order is Pre-session
  Scanner → Archive → Tracker.

Full design: [pre-session-equity-tool-design.md](pre-session-equity-tool-design.md)
