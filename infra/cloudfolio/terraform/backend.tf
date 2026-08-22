terraform {
  # Bucket + region come from ../../backend.hcl (shared across all tools).
  # Key is passed at `terraform init` time — see deploy.sh / destroy.sh.
  backend "s3" {}
}
