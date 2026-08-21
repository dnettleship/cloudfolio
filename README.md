# cloudfolio

Personal finance tools — a stock tracker with a web frontend deployed on AWS.

## What it does

**Portfolio tracker**: compares the returns of a chosen basket of stocks against the VWRA.L index over a configurable lookback period. GBP/USD forex adjustments are applied to USD-denominated holdings so all series are comparable in GBP terms.

Results are available as:
- JSON or chart output from the local CLI (`tracker/`)
- A web UI served over HTTPS via CloudFront, backed by a Lambda API

## Project structure

```
tracker/        Local CLI tools (tracker.py, chart.py, baskets.json)
infra/          AWS infrastructure (Lambda, API Gateway, S3 frontend)
```

## Tracker (local)

```bash
python3 tracker/tracker.py --basket <id>          # JSON summary to stdout
python3 tracker/chart.py --basket <id>            # saves performance_chart_<id>.png
python3 tracker/chart.py --basket <id> --days 365 # 1-year chart
```

Baskets are defined in [tracker/baskets.json](tracker/baskets.json). `--days` defaults to 30, max 3650.

## Infrastructure (AWS)

The web app is a Lambda container fronted by API Gateway, with one endpoint:

| Route | Purpose |
|---|---|
| `POST /report` | Tracker — returns GBP-adjusted performance table, summary stats, and chart |

The frontend is a static HTML file in a private S3 bucket served over HTTPS via CloudFront.

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
