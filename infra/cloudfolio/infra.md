# Cloudfolio — Infrastructure

AWS deployment for the Cloudfolio stock tracker. The backend runs as a Lambda container and is fronted by an API Gateway HTTP API. The frontend is a static HTML page served from S3 via CloudFront (HTTPS).

The frontend also has a second tab that calls a separate tool's API — [`infra/pre-session-scanner`](../pre-session-scanner/infra.md) — deployed and destroyed independently of this stack. See that doc for its own deploy process and the `PRESESSION_API_URL` constant in `frontend/index.html`.

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
| Terraform state | S3 | `terraform-state-304707804854` (shared bucket, key `cloudfolio/terraform.tfstate` — see [../README.md](../README.md)) |
| CI deploy role | IAM Role | `cloudfolio-github-actions` |

## CI/CD

There's no local deploy/destroy script — both are GitHub Actions workflows, authenticated to AWS via OIDC (GitHub issues a short-lived token exchanged for the `cloudfolio-github-actions` IAM role; no AWS credentials are stored in GitHub). The role's trust policy restricts `AssumeRoleWithWebIdentity` to `repo:dnettleship/cloudfolio:ref:refs/heads/main` (defined in `terraform/github_oidc.tf`), and its permissions are scoped to the specific `cloudfolio` resources (ECR repo, Lambda function, lambda execution role, site bucket) rather than account-wide access.

The GitHub OIDC provider itself (`token.actions.githubusercontent.com`) is a single resource per AWS account and pre-existed from another project, so it's referenced via a Terraform data source rather than managed here — see the comment in `github_oidc.tf` before adding a similar setup for another tool.

### Deploy

[`.github/workflows/deploy.yml`](../../.github/workflows/deploy.yml) runs automatically on every push to `main` (no path filter — any push redeploys). It can also be triggered manually from the Actions tab (`workflow_dispatch`) with a `mode` input:

- **`full`** (default) — provisions ECR, builds & pushes the Docker image, force-updates the Lambda function code (skipped if the function doesn't exist yet — e.g. a first-ever deploy or a redeploy after `destroy.yml`, since Terraform creates it fresh with the just-pushed image), applies the rest of Terraform, then uploads the frontend
- **`upload-only`** — skips Docker/Terraform entirely and just re-injects `__API_URL__` / `__BASKETS_JSON__` into `index.html` and uploads to S3. Use this after a `tracker/baskets.json`-only change, since a full redeploy isn't needed for that.

Both modes finish by injecting the API Gateway URL and the baskets from [`tracker/baskets.json`](../../tracker/baskets.json) into `index.html`. The run's summary page prints the site URL and API endpoint.

### Destroy

[`.github/workflows/destroy.yml`](../../.github/workflows/destroy.yml) is manual-only (`workflow_dispatch`, triggered from the Actions tab). It empties the S3 site bucket, then runs `terraform destroy` — targeted to exclude the `cloudfolio-github-actions` IAM role/policy, since destroying the role the workflow is currently running as would fail (and would strand future deploys). There's no typed confirmation step; triggering the workflow run is the confirmation. The Terraform *state bucket* is never touched by either workflow.

### Local Terraform (bypassing CI)

Needed to fix the CI role's own permissions (its policy deliberately can't modify itself — see `github_oidc.tf`) or for anything else CI can't do. Requires AWS CLI configured, Docker running (image builds only), and Terraform >= 1.5:

```bash
cd infra/cloudfolio/terraform
terraform init -reconfigure \
  -backend-config="../../backend.hcl" \
  -backend-config="key=cloudfolio/terraform.tfstate"
terraform apply
```

## File structure

```
infra/cloudfolio/
  app/
    Dockerfile           Lambda container image (Python 3.12)
    lambda_handler.py    Backend: tracker + chart logic, API handler
    requirements.txt     Pinned Python dependencies
  frontend/
    index.html           Single-page app (API URL injected at deploy time)
  terraform/
    backend.tf           S3 remote state config (bucket/region from ../../backend.hcl)
    variables.tf         aws_region, project name, github_repo
    main.tf              All AWS resource definitions
    github_oidc.tf       GitHub Actions OIDC trust + CI deploy role/policy
    outputs.tf           site_url, api_url, ecr_repository_url, site_bucket, github_actions_role_arn
```

Deploy/destroy logic lives in [`.github/workflows/`](../../.github/workflows/) (`deploy.yml`, `destroy.yml`), not in this directory.

This is one of possibly several tool subfolders under `infra/`, all sharing the state bucket defined in `infra/backend.hcl`. See [../README.md](../README.md) for the shared layout.

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
| `github_repo` | `dnettleship/cloudfolio` | Repo allowed to assume the CI deploy role (`owner/repo`) |

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
