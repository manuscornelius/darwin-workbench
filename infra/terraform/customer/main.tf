terraform {
  required_version = ">= 1.5.0"
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

# Store customer BPC credentials in Secrets Manager
resource "aws_secretsmanager_secret" "customer_bpc" {
  name        = "darwin-workbench/customers/${var.customer_name}/bpc"
  description = "BPC credentials for ${var.customer_full}"

  tags = {
    Project      = "darwin-workbench"
    Customer     = var.customer_name
    CustomerFull = var.customer_full
  }
}

resource "aws_secretsmanager_secret_version" "customer_bpc" {
  secret_id = aws_secretsmanager_secret.customer_bpc.id

  secret_string = jsonencode({
    server_url  = var.bpc_server_url
    username    = var.bpc_username
    password    = var.bpc_password
    environment = var.bpc_environment
  })
}