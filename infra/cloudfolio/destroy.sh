#!/usr/bin/env bash
# Tear down all Cloudfolio AWS infrastructure.
#
# This will permanently delete:
#   - The S3 site bucket and its contents
#   - The ECR repository and all images
#   - The Lambda function
#   - The API Gateway
#   - IAM roles created by this project
#
# The Terraform state bucket (terraform-state-304707804854) is NOT touched.
#
# Usage:
#   cd infra/cloudfolio
#   ./destroy.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TF_DIR="$SCRIPT_DIR/terraform"
BACKEND_HCL="$SCRIPT_DIR/../backend.hcl"
STATE_KEY="cloudfolio/terraform.tfstate"

# ── Confirmation prompt ───────────────────────────────────────────────────────

echo "WARNING: This will destroy all Cloudfolio infrastructure."
read -r -p "Type 'yes' to continue: " confirm
if [[ "$confirm" != "yes" ]]; then
  echo "Aborted."
  exit 0
fi

# ── Empty the site bucket (S3 destroy fails if bucket is non-empty) ───────────

echo ""
echo "==> [1/2] Emptying S3 site bucket..."
cd "$TF_DIR"
terraform init -reconfigure \
  -backend-config="$BACKEND_HCL" \
  -backend-config="key=$STATE_KEY"

SITE_BUCKET=$(terraform output -raw site_bucket 2>/dev/null || echo "")
if [[ -n "$SITE_BUCKET" ]]; then
  aws s3 rm "s3://$SITE_BUCKET" --recursive
  echo "Emptied s3://$SITE_BUCKET"
else
  echo "Could not read site bucket from state — skipping empty step"
fi

# ── Terraform destroy ─────────────────────────────────────────────────────────

echo ""
echo "==> [2/2] Running terraform destroy..."
terraform destroy -auto-approve

echo ""
echo "✓ All Cloudfolio infrastructure destroyed."
