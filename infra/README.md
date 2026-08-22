# Infrastructure

Each tool that gets deployed to AWS lives in its own subfolder here (`infra/cloudfolio/`, and more to come). Every subfolder is a self-contained Terraform root module. There are no local deploy/destroy scripts — deploy and destroy both run as GitHub Actions workflows in [`.github/workflows/`](../.github/workflows/) (`deploy.yml`, `destroy.yml`), authenticated to AWS via OIDC.

What's shared across all of them:

- **State bucket** — `infra/backend.hcl` holds the S3 bucket + region used for Terraform remote state. Each tool passes its own state `key` (e.g. `cloudfolio/terraform.tfstate`) at `terraform init` time, so every tool gets an isolated state file inside the same bucket. See any tool's deploy workflow for the exact `-backend-config` flags.
- **GitHub Actions OIDC provider** — `token.actions.githubusercontent.com` is a single resource per AWS account and already exists (pre-dates this repo). Don't create a second `aws_iam_openid_connect_provider` for a new tool's CI role — reference the existing one via a data source instead, as `infra/cloudfolio/terraform/github_oidc.tf` does. Each tool should still create its own CI deploy role scoped to its own resources.

To add a new tool, create `infra/<tool>/` with its own `app/` and `terraform/` (with an empty `backend "s3" {}` block — see `infra/cloudfolio/terraform/backend.tf`), following the `cloudfolio` subfolder as a template. If it needs CI auto-deploy, also add `.github/workflows/<tool>-deploy.yml` / `<tool>-destroy.yml` (path-filtered to that tool's directories, unlike cloudfolio's unfiltered deploy trigger) and its own `github_oidc.tf`.

See [cloudfolio/infra.md](cloudfolio/infra.md) for the tracker deployment specifically.
