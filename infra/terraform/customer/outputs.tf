output "workspace_id" {
  description = "Customer Workspace ID"
  value       = aws_workspaces_workspace.customer.id
}

output "workspace_ip" {
  description = "Customer Workspace IP address"
  value       = aws_workspaces_workspace.customer.ip_address
}

output "workspace_username" {
  description = "AD username for the customer Workspace"
  value       = "${var.customer_name}-user"
}

output "bpc_secret_arn" {
  description = "ARN of the customer BPC credentials secret"
  value       = aws_secretsmanager_secret.customer_bpc.arn
}

output "customer_name" {
  description = "Customer slug"
  value       = var.customer_name
}
