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
  name = "${var.project}-secrets-read"
  role = aws_iam_role.lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "secretsmanager:GetSecretValue"
      Resource = aws_secretsmanager_secret.anthropic_api_key.arn
    }]
  })
}

# ── Secrets ──────────────────────────────────────────────────────────────────

# Value is set out-of-band via `aws secretsmanager put-secret-value` — never
# committed to Terraform state as a secret_version resource.
resource "aws_secretsmanager_secret" "anthropic_api_key" {
  name = "${var.project}-anthropic-api-key"
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
      ANTHROPIC_API_KEY_SECRET_NAME = aws_secretsmanager_secret.anthropic_api_key.name
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

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.app.id
  name        = "$default"
  auto_deploy = true
}

resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.app.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.app.execution_arn}/*/*"
}
