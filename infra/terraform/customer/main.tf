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

# Reuse the shared Performance bundle
data "aws_workspaces_bundle" "performance" {
  bundle_id = "wsb-gm4d5tx2v"
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

# Provision the customer Workspace
# aws_workspaces_workspace creates the AD user automatically
# if it does not already exist in the directory
resource "aws_workspaces_workspace" "customer" {
  directory_id = var.directory_id
  bundle_id    = data.aws_workspaces_bundle.performance.id
  user_name    = "${var.customer_name}-user"

  workspace_properties {
    running_mode                              = "AUTO_STOP"
    running_mode_auto_stop_timeout_in_minutes = 60
    root_volume_size_gib                      = 80
    user_volume_size_gib                      = 50
    compute_type_name                         = "PERFORMANCE"
  }

  tags = {
    Project      = "darwin-workbench"
    Customer     = var.customer_name
    CustomerFull = var.customer_full
    Environment  = "prod"
  }
}
