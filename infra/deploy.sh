#!/usr/bin/env bash
# Deploy Cloudfolio to AWS.
#
# Prerequisites:
#   - AWS CLI configured (aws configure / env vars)
#   - Docker running
#   - Terraform >= 1.5 installed
#
# Usage:
#   cd infra
#   ./deploy.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TF_DIR="$SCRIPT_DIR/terraform"

UPLOAD_ONLY=false
if [[ "${1:-}" == "--upload-only" ]]; then
  UPLOAD_ONLY=true
fi

# ── Resolve AWS context ───────────────────────────────────────────────────────

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION=$(aws configure get region 2>/dev/null || echo "eu-west-2")
echo "Account: $ACCOUNT_ID  Region: $REGION"

# ── Upload-only path ──────────────────────────────────────────────────────────

if [[ "$UPLOAD_ONLY" == true ]]; then
  echo ""
  echo "==> Upload-only mode: reading outputs from existing Terraform state..."
  cd "$TF_DIR"
  API_URL=$(terraform output -raw api_url)
  SITE_BUCKET=$(terraform output -raw site_bucket)
  SITE_URL=$(terraform output -raw site_url)

  FRONTEND_TMP=$(mktemp /tmp/index.XXXXXX.html)
  trap 'rm -f "$FRONTEND_TMP"' EXIT

  python3 -c "
import sys, pathlib
src = pathlib.Path(sys.argv[1]).read_text()
pathlib.Path(sys.argv[2]).write_text(src.replace('__API_URL__', sys.argv[3]))
" "$SCRIPT_DIR/frontend/index.html" "$FRONTEND_TMP" "$API_URL"

  aws s3 cp "$FRONTEND_TMP" "s3://$SITE_BUCKET/index.html" \
    --content-type "text/html" \
    --cache-control "no-cache"

  echo ""
  echo "✓ Frontend uploaded"
  echo "  Site: $SITE_URL"
  exit 0
fi

# ── Step 1: Create ECR repo (must exist before Docker push) ──────────────────

echo ""
echo "==> [1/4] Provisioning ECR repository..."
cd "$TF_DIR"
terraform init -reconfigure
terraform apply -target=aws_ecr_repository.app -auto-approve

ECR_URL=$(terraform output -raw ecr_repository_url)
echo "ECR: $ECR_URL"

# ── Step 2: Build and push Docker image ──────────────────────────────────────

echo ""
echo "==> [2/4] Building and pushing Docker image..."

# Use a temp Docker config dir to avoid macOS credential store errors.
# The ECR password is written to a plain config.json rather than the keychain.
DOCKER_CONFIG_TMP=$(mktemp -d)
FRONTEND_TMP=$(mktemp /tmp/index.XXXXXX.html)
trap 'rm -rf "$DOCKER_CONFIG_TMP"; rm -f "$FRONTEND_TMP"' EXIT
echo '{"credsStore":""}' > "$DOCKER_CONFIG_TMP/config.json"

aws ecr get-login-password --region "$REGION" \
  | DOCKER_CONFIG="$DOCKER_CONFIG_TMP" docker login \
      --username AWS \
      --password-stdin \
      "$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com"

# Build from repo root so COPY paths in Dockerfile resolve correctly
DOCKER_CONFIG="$DOCKER_CONFIG_TMP" docker build \
  --platform linux/amd64 \
  -f "$SCRIPT_DIR/app/Dockerfile" \
  -t "$ECR_URL:latest" \
  "$REPO_ROOT"

DOCKER_CONFIG="$DOCKER_CONFIG_TMP" docker push "$ECR_URL:latest"

# Force Lambda to pull the new image — Terraform won't do this automatically
# when the tag (:latest) hasn't changed, even if the underlying image has.
echo "Updating Lambda function code..."
aws lambda update-function-code \
  --function-name cloudfolio \
  --image-uri "$ECR_URL:latest" \
  --region "$REGION" \
  --output json | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  Lambda updated: {d[\"LastUpdateStatus\"]}')"

# ── Step 3: Apply remaining Terraform ────────────────────────────────────────

echo ""
echo "==> [3/4] Applying Terraform (full)..."
terraform apply -auto-approve

API_URL=$(terraform output -raw api_url)
SITE_BUCKET=$(terraform output -raw site_bucket)
SITE_URL=$(terraform output -raw site_url)

# ── Step 4: Upload frontend with API URL injected ────────────────────────────

echo ""
echo "==> [4/4] Uploading frontend to s3://$SITE_BUCKET..."

python3 -c "
import sys, pathlib
src = pathlib.Path(sys.argv[1]).read_text()
pathlib.Path(sys.argv[2]).write_text(src.replace('__API_URL__', sys.argv[3]))
" "$SCRIPT_DIR/frontend/index.html" "$FRONTEND_TMP" "$API_URL"

aws s3 cp "$FRONTEND_TMP" "s3://$SITE_BUCKET/index.html" \
  --content-type "text/html" \
  --cache-control "no-cache"

echo "Uploaded index.html → s3://$SITE_BUCKET"

echo ""
echo "✓ Deployed successfully"
echo "  Site: $SITE_URL"
echo "  API:  $API_URL/report"
