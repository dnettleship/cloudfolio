# GitHub Actions OIDC trust — lets the deploy.yml workflow assume an AWS role
# without any long-lived credentials stored in GitHub.
#
# The OIDC provider (token.actions.githubusercontent.com) is a single resource
# per AWS account and already exists here (set up by another project in this
# account), so it's referenced as a data source rather than managed as a
# resource — we don't want Terraform mutating a shared, account-wide IAM
# resource that other roles/projects may depend on. Any future tool under
# infra/<tool>/ that needs GitHub Actions access should do the same.

data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

resource "aws_iam_role" "github_actions" {
  name = "${var.project}-github-actions"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = data.aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        StringLike = {
          # Only the main branch of this repo can assume the role — not PRs,
          # not other branches, not forks.
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_repo}:ref:refs/heads/main"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "github_actions_deploy" {
  name = "${var.project}-deploy"
  role = aws_iam_role.github_actions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "TerraformState"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
        Resource = ["arn:aws:s3:::terraform-state-${data.aws_caller_identity.current.account_id}", "arn:aws:s3:::terraform-state-${data.aws_caller_identity.current.account_id}/*"]
      },
      {
        Sid      = "EcrAuth"
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Sid      = "EcrRepo"
        Effect   = "Allow"
        Action   = ["ecr:*"]
        Resource = "arn:aws:ecr:${var.aws_region}:${data.aws_caller_identity.current.account_id}:repository/${var.project}"
      },
      {
        Sid      = "Lambda"
        Effect   = "Allow"
        Action   = ["lambda:*"]
        Resource = "arn:aws:lambda:${var.aws_region}:${data.aws_caller_identity.current.account_id}:function:${var.project}"
      },
      {
        # Needed to resolve the OIDC provider data source by URL — this is an
        # account-wide list action, IAM doesn't support resource scoping here.
        Sid      = "OidcProviderLookup"
        Effect   = "Allow"
        Action   = ["iam:ListOpenIDConnectProviders", "iam:GetOpenIDConnectProvider"]
        Resource = "*"
      },
      {
        Sid    = "LambdaExecutionRole"
        Effect = "Allow"
        Action = [
          "iam:GetRole", "iam:CreateRole", "iam:DeleteRole", "iam:TagRole",
          "iam:PutRolePolicy", "iam:DeleteRolePolicy", "iam:GetRolePolicy",
          "iam:AttachRolePolicy", "iam:DetachRolePolicy", "iam:ListAttachedRolePolicies", "iam:ListRolePolicies",
          "iam:ListInstanceProfilesForRole", # checked by the AWS provider before it will delete a role
          "iam:PassRole",
        ]
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.project}-lambda-role"
      },
      {
        # Read-only on its own role/policy — enough for Terraform to refresh
        # state on a routine apply. Deliberately excludes Put/Attach/Delete on
        # itself: a CI role that can rewrite its own permissions is a
        # privilege-escalation risk (a compromised push to main could grant
        # itself broader access). Changes to this role's own policy go
        # through a human running `terraform apply` locally instead.
        Sid      = "SelfRoleReadOnly"
        Effect   = "Allow"
        Action   = ["iam:GetRole", "iam:GetRolePolicy", "iam:ListAttachedRolePolicies", "iam:ListRolePolicies"]
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.project}-github-actions"
      },
      {
        Sid      = "ApiGateway"
        Effect   = "Allow"
        Action   = ["apigateway:*"]
        Resource = "*"
      },
      {
        Sid      = "SiteBucket"
        Effect   = "Allow"
        Action   = ["s3:*"]
        Resource = ["arn:aws:s3:::${var.project}-site-${data.aws_caller_identity.current.account_id}", "arn:aws:s3:::${var.project}-site-${data.aws_caller_identity.current.account_id}/*"]
      },
      {
        Sid      = "CloudFront"
        Effect   = "Allow"
        Action   = ["cloudfront:*"]
        Resource = "*"
      },
      {
        Sid      = "StsIdentity"
        Effect   = "Allow"
        Action   = ["sts:GetCallerIdentity"]
        Resource = "*"
      },
    ]
  })
}

output "github_actions_role_arn" {
  value = aws_iam_role.github_actions.arn
}
