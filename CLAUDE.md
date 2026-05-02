# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Local tracker

```bash
python3 tracker/tracker.py --basket tech-us                  # JSON summary to stdout
python3 tracker/tracker.py --basket commodities

python3 tracker/chart.py --basket tech-us                    # saves performance_chart_tech-us.png
python3 tracker/chart.py --basket tech-us --days 365         # 1-year chart
```

`--days` defaults to 30, max 3650.

### Local DCF analyser

```bash
python3 tracker/dcf.py AAPL                                  # single ticker
python3 tracker/dcf.py AAPL MSFT GOOGL                       # multiple tickers
python3 tracker/dcf.py AAPL --discount-rate 0.09 --terminal-growth 0.025
python3 tracker/dcf.py AAPL --growth-rate 0.15               # override inferred growth
```

Prints intrinsic value, margin of safety, key multiples, quality metrics, DCF assumptions, and a 3×3 sensitivity table (bear/base/bull growth × ±1 pp discount rate). Growth rate is inferred from yfinance in this order: analyst 5yr EPS estimate → TTM earnings growth → TTM revenue growth → 10% default. `--discount-rate` defaults to 0.10, `--terminal-growth` to 0.03.

No test suite or linter is configured.

### Infrastructure

All infra commands must be run from the `infra/` directory:

```bash
cd infra && ./deploy.sh               # full provision + deploy
cd infra && ./deploy.sh --upload-only # re-upload frontend only (no Terraform/Docker)
cd infra && ./destroy.sh              # tear down all AWS resources
```

`deploy.sh` requires AWS CLI configured, Docker running, and Terraform >= 1.5.

## Architecture

There are two independent execution paths that share the same financial logic:

**Local CLI** (`tracker/`): `tracker.py` and `chart.py` are standalone scripts. Both read basket definitions from `baskets.json` and call yfinance directly. To add a basket, edit `baskets.json` only — no code changes needed.

**Web app** (`infra/`): `infra/app/lambda_handler.py` is a self-contained Lambda handler with two routes:

- `POST /report` — tracker: returns GBP-adjusted performance table, summary stats, and a base64-encoded PNG chart.
- `POST /dcf` — DCF analyser: accepts `{ tickers, discount_rate, terminal_growth, growth_rate? }` and returns per-ticker fundamentals, intrinsic value, and a 3×3 sensitivity table.

Routing is done inside `handler()` via `event["rawPath"]`. The frontend is a single static HTML file (`infra/frontend/index.html`) with all CSS and JS inline, split into two tabs (Portfolio Tracker / DCF Analyser). The placeholder `__API_URL__` in `index.html` is replaced at deploy time by `deploy.sh` with the live API Gateway URL before uploading to S3. The S3 bucket is private; access is via CloudFront (OAC) which serves the site over HTTPS at a `*.cloudfront.net` URL.

**Key divergence between CLI and Lambda**: The CLI uses `baskets.json` for currency mapping (explicit `"currency"` field per ticker). The Lambda infers currency from the ticker symbol — `.L` suffix → GBP, everything else → USD. If you add non-US, non-London-listed tickers via the web UI, this heuristic may give wrong results.

**DCF model** (shared logic between `tracker/dcf.py` and `lambda_handler.py`): 2-stage model — stage 1 (years 1–5) at the inferred/user-supplied growth rate, stage 2 (years 6–10) at `max(terminal_growth, stage1 × 0.5)`, then a Gordon Growth Model terminal value. Net cash (cash − debt) is added to enterprise value to derive equity value per share. The sensitivity table keys use 4 decimal places (`f"{value:.4f}"`) in both Python and the frontend's `toFixed(4)` to ensure consistent lookup.

**Forex adjustment**: All returns are normalised to GBP. USD-denominated tickers use `return_gbp = (end/start) × (gbpusd_start/gbpusd_end) - 1`. The `forex_adjustment_pp` field is the difference between GBP return and local return. For the time-series chart, forex is applied daily (not just start/end) by dividing price series by the GBPUSD series.

**Docker build context**: The Dockerfile uses `--platform linux/amd64` (Lambda requirement) and is built with the repo root as context (`docker build -f infra/app/Dockerfile .`), so `COPY` paths in the Dockerfile are relative to the repo root.

**CORS**: Lambda owns CORS entirely — every response includes `Access-Control-Allow-Origin: *` via `CORS_HEADERS`, and OPTIONS preflights are handled inside `handler()`. There is no `cors_configuration` block on the API Gateway Terraform resource; adding one would cause duplicate headers that browsers reject.
