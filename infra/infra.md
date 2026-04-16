# Cloudfolio — Infrastructure

AWS deployment for the Cloudfolio stock tracker. The backend runs as a Lambda container and is fronted by an API Gateway HTTP API. The frontend is a static HTML page served from S3 via CloudFront (HTTPS).

## Architecture

```
Browser
  │
  ├── GET  →  CloudFront  →  S3 (private bucket, OAC)  (index.html)
  │
  └── POST /report  →  API Gateway (HTTP API)
                              │
                        Lambda (container)
                              │
                         yfinance API
```

| Component | AWS Service | Name |
|---|---|---|
| Frontend CDN | CloudFront | `*.cloudfront.net` |
| Frontend storage | S3 (private) | `cloudfolio-site-<account_id>` |
| Container registry | ECR | `cloudfolio` |
| Backend | Lambda (container image) | `cloudfolio` |
| API | API Gateway HTTP API | `cloudfolio` |
| Execution role | IAM Role | `cloudfolio-lambda-role` |
| Terraform state | S3 | `terraform-state-304707804854` |

## Prerequisites

- AWS CLI configured (`aws configure` or environment variables)
- Docker running locally
- Terraform >= 1.5
- Python 3.x (used by `deploy.sh` for URL injection)

## Deploy

```bash
cd infra
./deploy.sh
```

The script runs four steps:

1. **Provision ECR** — `terraform apply -target=aws_ecr_repository.app`
2. **Build & push image** — Docker build from repo root, push to ECR
3. **Apply Terraform** — creates all remaining resources
4. **Upload frontend** — injects the API Gateway URL into `index.html` and uploads to S3

On completion the script prints the site URL and API endpoint.

## Destroy

```bash
cd infra
./destroy.sh
```

Prompts for confirmation, empties the S3 site bucket, then runs `terraform destroy`. The Terraform state bucket is never touched.

## File structure

```
infra/
  app/
    Dockerfile           Lambda container image (Python 3.12)
    lambda_handler.py    Backend: tracker + chart logic, API handler
    requirements.txt     Pinned Python dependencies
  frontend/
    index.html           Single-page app (API URL injected at deploy time)
  terraform/
    backend.tf           S3 remote state configuration
    variables.tf         aws_region, project name
    main.tf              All AWS resource definitions
    outputs.tf           site_url, api_url, ecr_repository_url, site_bucket
  deploy.sh              End-to-end deploy script
  destroy.sh             Tear down all infrastructure
```

## API

**`POST /report`**

Request body:

```json
{
  "tickers": ["MSFT", "META", "AMZN"],
  "index":   "VWRA.L",
  "days":    30
}
```

Response:

```json
{
  "summary":       { ... },
  "rows":          [ ... ],
  "chart_base64":  "<png as base64>"
}
```

See [tracker/tracker.md](../tracker/tracker.md) for full field definitions.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `aws_region` | `eu-west-2` | Region to deploy into |
| `project` | `cloudfolio` | Prefix used for all resource names |

Override at plan/apply time:

```bash
terraform -chdir=terraform apply -var="aws_region=us-east-1"
```

## Lambda notes

- **Runtime**: Python 3.12 container image
- **Memory**: 1024 MB
- **Timeout**: 120 seconds (allows for slow yfinance fetches and matplotlib rendering)
- **`MPLCONFIGDIR`**: set to `/tmp` so matplotlib can write its font cache in the Lambda execution environment

## Cost estimate

Costs for personal or small-team use. All figures are monthly.

### Per-service breakdown

| Service | What drives cost | Est. cost |
|---|---|---|
| ECR | ~700 MB image at $0.10/GB | ~$0.07/month |
| S3 | ~10 KB HTML file + request fees | ~$0.00 |
| CloudFront | 1 TB/month free tier; $0.0085/GB after | ~$0.00 at low volume |
| Lambda | See table below | Free tier at low volume |
| API Gateway | $1.00/million requests + $0.09/GB data out | ~$0.00 at low volume |

**ECR image storage is the only fixed cost** — ~$0.07/month regardless of usage.

### Lambda cost by usage

Each report generation takes roughly 15–20 seconds at 1,024 MB = ~20 GB-seconds per request. The Lambda free tier covers 400,000 GB-seconds/month per account (~20,000 reports).

| Monthly reports | Lambda | API Gateway | ECR | **Total** |
|---|---|---|---|---|
| 10 | Free tier | ~$0.00 | ~$0.08 | **~$0.08** |
| 100 | Free tier | ~$0.00 | ~$0.08 | **~$0.09** |
| 1,000 | Free tier | ~$0.03 | ~$0.08 | **~$0.11** |
| 10,000 | Free tier | ~$0.27 | ~$0.08 | **~$0.35** |
| 50,000 | ~$10.00 | ~$1.35 | ~$0.08 | **~$11.50** |

### Notes

- **No VPC / NAT Gateway** — keeping Lambda in the default network avoids ~$32/month per NAT Gateway, which is typically the largest surprise cost in Lambda deployments
- **Cold starts** — container image cold starts add 5–15s on the first request after a period of inactivity; this doesn't affect cost but is noticeable in the UI. Provisioned concurrency would eliminate it but costs ~$45/month for a single instance — not worthwhile at this scale
- **API Gateway response payload** — each response carries a base64 PNG (~300 KB) + JSON (~5 KB); data transfer out is charged at $0.09/GB beyond the free tier
