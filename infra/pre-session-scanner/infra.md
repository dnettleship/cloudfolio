# Pre-session scanner — Infrastructure

AWS deployment for the pre-session scanner's backend. A single Lambda
(container image) fronted by an API Gateway HTTP API, with one route:

**`POST /scan`** — runs `pre-session-scanner/scanner.py`'s `build_result()`
live (no scheduling yet — this is Phase 1, on-demand only) and returns the
same JSON the CLI prints. Request body: `{"run_type": "on-demand"}`
(optional, defaults to `"on-demand"`).

No frontend of its own — it's called from the Cloudfolio site's
"Pre-session Scanner" tab (`infra/cloudfolio/frontend/index.html`), which
hardcodes this stack's API URL as `PRESESSION_API_URL`. **If this stack is
ever destroyed and recreated, update that constant** — unlike cloudfolio's
own `__API_URL__`, it isn't injected at deploy time (deliberately, to avoid
coupling the two tools' deploy processes together).

## Deploy

No CI yet — deploy locally:

```bash
cd infra/pre-session-scanner/terraform
terraform init -reconfigure \
  -backend-config="../../backend.hcl" \
  -backend-config="key=pre-session-scanner/terraform.tfstate"
terraform apply -target=aws_ecr_repository.app -auto-approve

# from repo root — build reuses pre-session-scanner/*.py directly, see Dockerfile
ECR_URL=$(terraform -chdir=infra/pre-session-scanner/terraform output -raw ecr_repository_url)
aws ecr get-login-password --region eu-west-2 | docker login --username AWS --password-stdin "${ECR_URL%%/*}"
docker build --platform linux/amd64 -f infra/pre-session-scanner/app/Dockerfile -t "${ECR_URL}:latest" .
docker push "${ECR_URL}:latest"

cd infra/pre-session-scanner/terraform && terraform apply -auto-approve
```

(Note: unbraced `$ECR_URL:latest` breaks under zsh — it gets parsed as a
history-modifier suffix (`:l` = lowercase) rather than a literal colon.
Always brace it: `${ECR_URL}:latest`. Bash doesn't have this problem, but
these are typed ad hoc, not run via a `.sh` script, so it matters here.)

## File structure

```
infra/pre-session-scanner/
  app/
    Dockerfile           Lambda container image (Python 3.12)
    lambda_handler.py    Thin handler — calls scanner.build_result()
    requirements.txt     yfinance, pandas, numpy
  terraform/
    backend.tf           S3 remote state config (bucket/region from ../../backend.hcl)
    variables.tf          aws_region, project name
    main.tf               ECR, IAM, Lambda, API Gateway
    outputs.tf             api_url, ecr_repository_url
```

The Docker build copies `pre-session-scanner/{scanner,dashboard}.py` and
`watchlist.json` directly from the repo root into the image — the Lambda
runs the *same* code as the CLI, not a reimplementation of it. `dashboard.py`
is copied because `scanner.py` imports it at module load time, even though
the Lambda handler only calls `scanner.build_result()`, not the
file-writing `dashboard.write()`.

## Configuration

| Variable | Default |
|---|---|
| `aws_region` | `eu-west-2` |
| `project` | `pre-session-scanner` |

## Lambda notes

- **Memory**: 512 MB (no matplotlib/chart rendering here, unlike cloudfolio)
- **Timeout**: 180s — ~20 sequential `yfinance` calls (VIX, watchlist breadth,
  oil/gold, screener); no batching yet, matching `scanner.py`'s CLI-simple style

See [../../pre-session-scanner/pre-session.md](../../pre-session-scanner/pre-session.md)
for the tool itself and [../README.md](../README.md) for the shared infra layout.
