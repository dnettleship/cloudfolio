# Infrastructure

Each tool that gets deployed to AWS lives in its own subfolder here (`infra/cloudfolio/`, and more to come). Every subfolder is a self-contained Terraform root module with its own `deploy.sh` / `destroy.sh`, so tools can be deployed and destroyed independently.

What's shared across all of them:

- **State bucket** — `infra/backend.hcl` holds the S3 bucket + region used for Terraform remote state. Each tool passes its own state `key` (e.g. `cloudfolio/terraform.tfstate`) at `terraform init` time, so every tool gets an isolated state file inside the same bucket. See any tool's `deploy.sh` for the exact `-backend-config` flags.

To add a new tool, create `infra/<tool>/` with its own `app/`, `terraform/` (with an empty `backend "s3" {}` block — see `infra/cloudfolio/terraform/backend.tf`), `deploy.sh`, and `destroy.sh`, following the `cloudfolio` subfolder as a template.

See [cloudfolio/infra.md](cloudfolio/infra.md) for the tracker deployment specifically.
