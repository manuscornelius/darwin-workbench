# DynamoDB table — single-table design
# Note: this provisions a second table for the provisioned environment.
# The existing darwin-workbench table in your account is the dev table.
resource "aws_dynamodb_table" "main" {
  name         = "${var.project}-${var.environment}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  attribute {
    name = "gsi1pk"
    type = "S"
  }

  attribute {
    name = "gsi1sk"
    type = "N"
  }

  global_secondary_index {
    name            = "gsi1"
    hash_key        = "gsi1pk"
    range_key       = "gsi1sk"
    projection_type = "ALL"
  }

  tags = {
    Project     = var.project
    Environment = var.environment
  }
}
