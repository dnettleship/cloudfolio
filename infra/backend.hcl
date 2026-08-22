# Shared Terraform state backend config, used by every tool subfolder
# (infra/<tool>/terraform/). The bucket and region are defined once here;
# each tool passes its own state key at `terraform init` time, e.g.:
#
#   terraform init -backend-config=../../backend.hcl -backend-config="key=<tool>/terraform.tfstate"
#
# See infra/README.md for the layout this supports.
bucket = "terraform-state-304707804854"
region = "eu-west-2"
