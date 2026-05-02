# cloudfolio

Personal finance tools — a stock tracker and DCF fundamental analyser with a web frontend deployed on AWS.

## What it does

**Portfolio tracker**: compares the returns of a chosen basket of stocks against the VWRA.L index over a configurable lookback period. GBP/USD forex adjustments are applied to USD-denominated holdings so all series are comparable in GBP terms.

**DCF analyser**: estimates intrinsic value per share using a 2-stage discounted cash flow model. Outputs key valuation multiples, quality metrics, and a sensitivity table across bear/base/bull growth scenarios and ±1 pp discount rates.

Results are available as:
- JSON or chart output from the local CLI (`tracker/`)
- A web UI served over HTTPS via CloudFront, backed by a Lambda API

## Project structure

```
tracker/        Local CLI tools (tracker.py, chart.py, dcf.py, baskets.json)
infra/          AWS infrastructure (Lambda, API Gateway, S3 frontend)
```

## Tracker (local)

```bash
python3 tracker/tracker.py --basket <id>          # JSON summary to stdout
python3 tracker/chart.py --basket <id>            # saves performance_chart_<id>.png
python3 tracker/chart.py --basket <id> --days 365 # 1-year chart
```

Baskets are defined in [tracker/baskets.json](tracker/baskets.json). `--days` defaults to 30, max 3650.

## DCF analyser (local)

```bash
python3 tracker/dcf.py AAPL MSFT GOOGL
python3 tracker/dcf.py AAPL --discount-rate 0.09 --terminal-growth 0.025
python3 tracker/dcf.py AAPL --growth-rate 0.15   # override inferred growth
```

Growth rate is inferred automatically (analyst estimate → TTM earnings growth → TTM revenue growth → 10% default). Default discount rate is 10%, terminal growth 3%.

## Infrastructure (AWS)

The web app is a Lambda container fronted by API Gateway, with two endpoints:

| Route | Purpose |
|---|---|
| `POST /report` | Tracker — returns GBP-adjusted performance table, summary stats, and chart |
| `POST /dcf` | DCF analyser — returns per-ticker intrinsic value, multiples, and sensitivity table |

The frontend is a static HTML file in a private S3 bucket served over HTTPS via CloudFront, with two tabs (Portfolio Tracker / DCF Analyser).

```bash
cd infra && ./deploy.sh               # provision and deploy everything
cd infra && ./deploy.sh --upload-only # re-upload frontend only
cd infra && ./destroy.sh              # tear down all resources
```

Requires AWS CLI configured, Docker running, and Terraform >= 1.5.

## Dependencies

- [yfinance](https://ranaroussi.github.io/yfinance/) — market data
- `matplotlib` — charting
- AWS (ECR, Lambda, API Gateway, S3, CloudFront), Terraform, Docker — cloud deployment
