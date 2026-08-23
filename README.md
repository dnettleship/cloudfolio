# cloudfolio

A personal collection of finance tools, each usable as a local CLI and (optionally) deployed as a small web app on AWS.

## Project structure

```
tracker/                Stock basket tracker — local CLI (tracker.py, chart.py, baskets.json)
pre-session-scanner/    Pre-session market conditions scanner — local CLI (scanner.py, dashboard.py)
infra/                  AWS infrastructure, one subfolder per deployable tool
```

Each tool's infra lives in its own `infra/<tool>/` subfolder — a self-contained Terraform setup deployed and torn down via GitHub Actions workflows, independently of other tools, while sharing a common Terraform state bucket. See [infra/README.md](infra/README.md) for how that's organised.

## Tools

| Tool | What it does | Docs |
|---|---|---|
| Tracker | Compares a basket of stocks against a benchmark index, with GBP/USD forex adjustment | [tracker/tracker.md](tracker/tracker.md), [infra/cloudfolio/infra.md](infra/cloudfolio/infra.md) |
| Pre-session scanner | Market conditions (volatility, breadth, oil/gold), a watchlist screener, and a Claude-written report, ahead of a trading session — evidence-first, with one explicit exception (see docs) | [pre-session-scanner/pre-session.md](pre-session-scanner/pre-session.md), [infra/pre-session-scanner/infra.md](infra/pre-session-scanner/infra.md) |

## Requirements

- Python 3.x for the local CLIs
- Deploying a web app happens via GitHub Actions (push to `main`) — no local AWS/Docker/Terraform setup needed for routine deploys. They're only needed for one-off local Terraform work; see each tool's infra docs.
