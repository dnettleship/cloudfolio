# cloudfolio

Personal finance tools — a stock basket tracker with a web frontend deployed on AWS.

## What it does

Compares the returns of a chosen basket of stocks against the VWRA.L index over a rolling 30-day period. GBP/USD forex adjustments are applied to USD-denominated holdings so all series are comparable.

Results are available as:
- JSON output from the CLI (`tracker/tracker.py`)
- A time-series chart (`tracker/chart.py`)
- A web UI served over HTTPS via CloudFront, backed by a Lambda API

## Project structure

```
tracker/        Local CLI tools (tracker.py, chart.py, baskets.json)
infra/          AWS infrastructure (Lambda, API Gateway, S3 frontend)
```

## Tracker (local)

```bash
python3 tracker/tracker.py --basket <id>   # prints JSON summary to stdout
python3 tracker/chart.py --basket <id>     # saves performance_chart_<id>.png
```

Baskets (sets of tickers to compare) are defined in [tracker/baskets.json](tracker/baskets.json). See [tracker/tracker.md](tracker/tracker.md) for full usage, output schema, and forex adjustment details.

## Infrastructure (AWS)

The web app runs as a Lambda container fronted by API Gateway. The frontend is a static HTML file in a private S3 bucket served over HTTPS via CloudFront.

```bash
cd infra && ./deploy.sh    # provision and deploy everything
cd infra && ./destroy.sh   # tear down all resources
```

See [infra/infra.md](infra/infra.md) for architecture, API docs, cost breakdown, and configuration.

## Dependencies

- [yfinance](https://ranaroussi.github.io/yfinance/) — market data
- `matplotlib` — charting
- AWS (ECR, Lambda, API Gateway, S3, CloudFront), Terraform, Docker — cloud deployment
