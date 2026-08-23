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

### Local pre-session scanner

```bash
python3 pre-session-scanner/scanner.py                    # JSON to stdout, writes dashboard.html + history/
python3 pre-session-scanner/scanner.py --run-type pre-open
```

Watchlist/config in `pre-session-scanner/watchlist.json`. `history/` and `dashboard.html` are gitignored (generated).

No test suite or linter is configured.

### Infrastructure

There are no local deploy scripts — all deploy/destroy logic lives in GitHub Actions workflows and runs in CI, authenticated to AWS via OIDC (no stored credentials):

- **`.github/workflows/deploy.yml`** — runs automatically on every push to `main` (full build/push/apply/upload, no path filter — any push redeploys). Can also be triggered manually (Actions tab → Run workflow) with a `mode` choice: `full` or `upload-only` (skips Docker/Terraform, just re-uploads the frontend — useful after a `tracker/baskets.json`-only change).
- **`.github/workflows/destroy.yml`** — manual only (`workflow_dispatch`), tears down all AWS resources for `cloudfolio` except the CI deploy role itself. No confirmation step — triggering the workflow run *is* the confirmation.

To change infra locally without going through CI (e.g. to fix the CI role's own permissions — see below), run Terraform directly from `infra/cloudfolio/terraform/`, initializing with `-backend-config="../../backend.hcl" -backend-config="key=cloudfolio/terraform.tfstate"`. Requires AWS CLI configured, Docker running (for image builds), and Terraform >= 1.5.

A broken commit on `main` goes live automatically — keep this in mind before pushing.

`infra/pre-session-scanner/` (the pre-session scanner's backend — `POST /scan`, `GET /archive`) has no CI yet — deploy locally, see `infra/pre-session-scanner/infra.md`. Its API URL is hardcoded in `infra/cloudfolio/frontend/index.html` as `PRESESSION_API_URL`, not injected at deploy time; update it there if that stack is ever destroyed/recreated. Needs an Anthropic API key in Secrets Manager (`pre-session-scanner-anthropic-api-key`, set out-of-band — see infra.md) for report generation to work; without it, scans still succeed with `report_error` set.

**zsh gotcha**: when typing ad hoc `docker build/push` commands (not inside a `.sh` script) directly in this shell, unbraced `$VAR:word` is parsed as a zsh history-modifier (e.g. `:latest` → `:l` = lowercase, silently eating the colon and the `l`). Always brace it: `"${ECR_URL}:latest"`, not `"$ECR_URL:latest"`. Bash scripts and GitHub Actions `run:` blocks aren't affected — only commands run directly in this zsh session.

## Architecture

`infra/` holds one subfolder per deployable tool (`infra/cloudfolio/`, `infra/pre-session-scanner/`), each a self-contained Terraform root module. They share a Terraform state bucket defined in `infra/backend.hcl`, with each tool using its own state key — see `infra/README.md`.

`infra/cloudfolio/frontend/index.html` is the umbrella site (tabbed UI — Pre-session Scanner, Archive, Tracker, in that nav order — dark theme) and calls both tools' APIs — cloudfolio's own `/report` (URL injected at deploy time) and pre-session-scanner's separate `/scan` + `/archive` (hardcoded, see above) — even though the two backends deploy independently. Known asymmetry: the tracker's backend lives under `infra/cloudfolio/` rather than its own `infra/tracker/`, unlike pre-session-scanner.

There are two independent execution paths that share the same tracker logic:

**Local CLI** (`tracker/`): `tracker.py` and `chart.py` are standalone scripts. Both read basket definitions from `baskets.json` and call yfinance directly. To add a basket, edit `baskets.json` only — no code changes needed.

**Web app** (`infra/cloudfolio/`): `infra/cloudfolio/app/lambda_handler.py` is a self-contained Lambda handler with one route:

- `POST /report` — tracker: returns GBP-adjusted performance table, summary stats, and a base64-encoded PNG chart.

The frontend is a single static HTML file (`infra/cloudfolio/frontend/index.html`) with all CSS and JS inline. Two placeholders are replaced at deploy time by the "Upload frontend" step in `deploy.yml` before uploading to S3: `__API_URL__` (the live API Gateway URL) and `__BASKETS_JSON__` (the contents of `tracker/baskets.json`, which populates the basket preset dropdown — this is baked in at deploy time, so editing `baskets.json` requires a redeploy for the web UI to pick it up, e.g. an `upload-only` manual run). The S3 bucket is private; access is via CloudFront (OAC) which serves the site over HTTPS at a `*.cloudfront.net` URL.

**Key divergence between CLI and Lambda**: The CLI uses `baskets.json` for currency mapping (explicit `"currency"` field per ticker). The Lambda infers currency from the ticker symbol — `.L` suffix → GBP, everything else → USD. If you add non-US, non-London-listed tickers via the web UI, this heuristic may give wrong results.

**Forex adjustment**: All returns are normalised to GBP. USD-denominated tickers use `return_gbp = (end/start) × (gbpusd_start/gbpusd_end) - 1`. The `forex_adjustment_pp` field is the difference between GBP return and local return. For the time-series chart, forex is applied daily (not just start/end) by dividing price series by the GBPUSD series.

**Docker build context**: The Dockerfile uses `--platform linux/amd64` (Lambda requirement) and is built with the repo root as context (`docker build -f infra/cloudfolio/app/Dockerfile .`), so `COPY` paths in the Dockerfile are relative to the repo root.

**CORS**: Lambda owns CORS entirely — every response includes `Access-Control-Allow-Origin: *` via `CORS_HEADERS`, and OPTIONS preflights are handled inside `handler()`. There is no `cors_configuration` block on the API Gateway Terraform resource; adding one would cause duplicate headers that browsers reject.

**Pre-session scanner** (`pre-session-scanner/`, `infra/pre-session-scanner/`): unlike the tracker, the Lambda handler (`infra/pre-session-scanner/app/lambda_handler.py`) does *not* reimplement the scan logic — the Dockerfile copies `pre-session-scanner/{scanner,dashboard,report}.py` straight into the image, and the handler calls `scanner.build_result(run_type)` then, on success, `report.generate_report(...)` (Claude Haiku 4.5) and archives the full result to S3. Same publish-gate rule as the design doc: the response's `publish_ok` field is `false` if a required dimension (volatility, breadth, commodities) failed — the frontend treats that as an error rather than rendering partial results; `report`/`report_error` and archiving only happen when the gate passes. See `pre-session-scanner/pre-session-equity-tool-design.md` for the full design and phased build plan (the report/archive additions are ahead of the phase plan — see that doc's Amendment and the "Written report" note under Dashboard + log); the rest of the code is Phase 1 only.
