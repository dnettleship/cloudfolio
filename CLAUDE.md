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

No test suite or linter is configured.

### Infrastructure

All infra commands must be run from the tool's subfolder under `infra/` (e.g. `infra/cloudfolio/`):

```bash
cd infra/cloudfolio && ./deploy.sh               # full provision + deploy
cd infra/cloudfolio && ./deploy.sh --upload-only # re-upload frontend only (no Terraform/Docker)
cd infra/cloudfolio && ./destroy.sh              # tear down all AWS resources
```

`deploy.sh` requires AWS CLI configured, Docker running, and Terraform >= 1.5.

## Architecture

`infra/` holds one subfolder per deployable tool (e.g. `infra/cloudfolio/`), each a self-contained Terraform root module with its own `deploy.sh`/`destroy.sh`. They share a Terraform state bucket defined in `infra/backend.hcl`, with each tool using its own state key — see `infra/README.md`. Currently `cloudfolio` is the only tool.

There are two independent execution paths that share the same tracker logic:

**Local CLI** (`tracker/`): `tracker.py` and `chart.py` are standalone scripts. Both read basket definitions from `baskets.json` and call yfinance directly. To add a basket, edit `baskets.json` only — no code changes needed.

**Web app** (`infra/cloudfolio/`): `infra/cloudfolio/app/lambda_handler.py` is a self-contained Lambda handler with one route:

- `POST /report` — tracker: returns GBP-adjusted performance table, summary stats, and a base64-encoded PNG chart.

The frontend is a single static HTML file (`infra/cloudfolio/frontend/index.html`) with all CSS and JS inline. Two placeholders are replaced at deploy time by `deploy.sh` before uploading to S3: `__API_URL__` (the live API Gateway URL) and `__BASKETS_JSON__` (the contents of `tracker/baskets.json`, which populates the basket preset dropdown — this is baked in at deploy time, so editing `baskets.json` requires a redeploy for the web UI to pick it up). The S3 bucket is private; access is via CloudFront (OAC) which serves the site over HTTPS at a `*.cloudfront.net` URL.

**Key divergence between CLI and Lambda**: The CLI uses `baskets.json` for currency mapping (explicit `"currency"` field per ticker). The Lambda infers currency from the ticker symbol — `.L` suffix → GBP, everything else → USD. If you add non-US, non-London-listed tickers via the web UI, this heuristic may give wrong results.

**Forex adjustment**: All returns are normalised to GBP. USD-denominated tickers use `return_gbp = (end/start) × (gbpusd_start/gbpusd_end) - 1`. The `forex_adjustment_pp` field is the difference between GBP return and local return. For the time-series chart, forex is applied daily (not just start/end) by dividing price series by the GBPUSD series.

**Docker build context**: The Dockerfile uses `--platform linux/amd64` (Lambda requirement) and is built with the repo root as context (`docker build -f infra/cloudfolio/app/Dockerfile .`), so `COPY` paths in the Dockerfile are relative to the repo root.

**CORS**: Lambda owns CORS entirely — every response includes `Access-Control-Allow-Origin: *` via `CORS_HEADERS`, and OPTIONS preflights are handled inside `handler()`. There is no `cors_configuration` block on the API Gateway Terraform resource; adding one would cause duplicate headers that browsers reject.
