terraform {
  backend "s3" {
    bucket = "terraform-state-304707804854"
    key    = "cloudfolio/terraform.tfstate"
    region = "eu-west-2"
  }
}
