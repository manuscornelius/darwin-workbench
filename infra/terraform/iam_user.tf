# IAM user for the council service running on the Workspace
# (Workspaces don't support EC2 instance profiles natively)
resource "aws_iam_user" "council_service" {
  name = "${var.project}-council-service"

  tags = {
    Project = var.project
  }
}

resource "aws_iam_user_policy" "council_service" {
  name = "${var.project}-council-service-policy"
  user = aws_iam_user.council_service.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "BedrockInvoke"
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream",
          "bedrock:Converse",
          "bedrock:ConverseStream",
        ]
        Resource = "*"
      },
      {
        Sid    = "DynamoDB"
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:GetItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:Query",
          "dynamodb:Scan",
        ]
        Resource = [
          aws_dynamodb_table.main.arn,
          "${aws_dynamodb_table.main.arn}/index/*",
        ]
      },
      {
        Sid    = "SecretsManager"
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret",
        ]
        Resource = aws_secretsmanager_secret.bpc_credentials.arn
      }
    ]
  })
}

resource "aws_iam_access_key" "council_service" {
  user = aws_iam_user.council_service.name
}

# Store the council service credentials in Secrets Manager
# so the Workspace startup script can pull them at boot
resource "aws_secretsmanager_secret" "council_credentials" {
  name        = "${var.project}/council-service-credentials"
  description = "AWS credentials for the Darwin Council service on Workspaces"

  tags = {
    Project = var.project
  }
}

resource "aws_secretsmanager_secret_version" "council_credentials" {
  secret_id = aws_secretsmanager_secret.council_credentials.id

  secret_string = jsonencode({
    aws_access_key_id     = aws_iam_access_key.council_service.id
    aws_secret_access_key = aws_iam_access_key.council_service.secret
    aws_region            = var.aws_region
  })
}
