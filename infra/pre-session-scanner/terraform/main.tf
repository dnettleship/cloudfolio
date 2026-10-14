terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}

# ── ECR ──────────────────────────────────────────────────────────────────────

resource "aws_ecr_repository" "app" {
  name         = var.project
  force_delete = true
}

# ── IAM ──────────────────────────────────────────────────────────────────────

resource "aws_iam_role" "lambda" {
  name = "${var.project}-lambda-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "lambda_secrets" {
  name = "${var.project}-api-key-read"
  role = aws_iam_role.lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "ssm:GetParameter"
      Resource = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${local.anthropic_api_key_parameter}"
    }]
  })
}

resource "aws_iam_role_policy" "lambda_archive" {
  name = "${var.project}-archive-access"
  role = aws_iam_role.lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:GetObject"]
        Resource = "${aws_s3_bucket.archive.arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = aws_s3_bucket.archive.arn
      },
    ]
  })
}

# ── API key ──────────────────────────────────────────────────────────────────

# The key is a SecureString SSM parameter created out-of-band with
# `aws ssm put-parameter` — Terraform only references its name, so the value
# never lands in state or git. (Encrypted with the default aws/ssm key.)
locals {
  anthropic_api_key_parameter = "/${var.project}/anthropic-api-key"
}

# ── S3 (private — report archive) ──────────────────────────────────────────

resource "aws_s3_bucket" "archive" {
  bucket = "${var.project}-archive-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "archive" {
  bucket                  = aws_s3_bucket.archive.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ── Lambda ───────────────────────────────────────────────────────────────────

resource "aws_lambda_function" "app" {
  function_name = var.project
  role          = aws_iam_role.lambda.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.app.repository_url}:latest"
  memory_size   = 512
  # ~20 sequential yfinance calls (VIX, watchlist breadth, oil/gold,
  # screener) — no matplotlib rendering here, but leaves headroom over the
  # local run time for a cold Lambda network path.
  timeout = 180

  environment {
    variables = {
      ANTHROPIC_API_KEY_PARAMETER_NAME = local.anthropic_api_key_parameter
      ARCHIVE_BUCKET_NAME              = aws_s3_bucket.archive.bucket
    }
  }
}

# ── API Gateway ───────────────────────────────────────────────────────────────

resource "aws_apigatewayv2_api" "app" {
  name          = var.project
  protocol_type = "HTTP"
  # No cors_configuration here — Lambda returns CORS headers on every
  # response (see infra/cloudfolio/terraform/main.tf for why).
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.app.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.app.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "scan" {
  api_id    = aws_apigatewayv2_api.app.id
  route_key = "POST /scan"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_route" "scan_options" {
  api_id    = aws_apigatewayv2_api.app.id
  route_key = "OPTIONS /scan"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_route" "archive" {
  api_id    = aws_apigatewayv2_api.app.id
  route_key = "GET /archive"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_route" "archive_options" {
  api_id    = aws_apigatewayv2_api.app.id
  route_key = "OPTIONS /archive"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.app.id
  name        = "$default"
  auto_deploy = true

  # Unauthenticated public API — /scan is expensive (~20 sequential yfinance
  # calls plus a Claude Haiku report call per request), so this caps runaway
  # or scripted traffic. Not per-IP, just an overall ceiling since there's no
  # WAF/usage plan in front of this.
  default_route_settings {
    throttling_burst_limit = 2
    throttling_rate_limit  = 1
  }
}

resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.app.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.app.execution_arn}/*/*"
}
