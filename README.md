# cloudfolio

A personal collection of finance tools, each usable as a local CLI and (optionally) deployed as a small web app on AWS.

## Project structure

```
tracker/        Stock basket tracker — local CLI (tracker.py, chart.py, baskets.json)
infra/          AWS infrastructure, one subfolder per deployable tool
```

Each tool's infra lives in its own `infra/<tool>/` subfolder — a self-contained Terraform setup with its own `deploy.sh`/`destroy.sh` — so tools can be deployed and torn down independently while sharing a common Terraform state bucket. See [infra/README.md](infra/README.md) for how that's organised.

## Tools

| Tool | What it does | Docs |
|---|---|---|
| Tracker | Compares a basket of stocks against a benchmark index, with GBP/USD forex adjustment | [tracker/tracker.md](tracker/tracker.md), [infra/cloudfolio/infra.md](infra/cloudfolio/infra.md) |

## Requirements

- Python 3.x for the local CLIs
- AWS CLI, Docker, and Terraform >= 1.5 for deploying any tool's web app
