variable "aws_region" {
  default = "eu-west-2"
}

variable "project" {
  default = "cloudfolio"
}

variable "github_repo" {
  description = "GitHub repo allowed to assume the deploy role, as owner/repo"
  default     = "dnettleship/cloudfolio"
}
