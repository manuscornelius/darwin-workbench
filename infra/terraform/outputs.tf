output "vpc_id" {
  description = "VPC ID"
  value       = aws_vpc.main.id
}

output "simple_ad_id" {
  description = "Simple AD directory ID"
  value       = aws_directory_service_directory.simple_ad.id
}

output "simple_ad_dns_ip_addrs" {
  description = "Simple AD DNS IP addresses"
  value       = aws_directory_service_directory.simple_ad.dns_ip_addresses
}

output "dynamodb_table_name" {
  description = "DynamoDB table name"
  value       = aws_dynamodb_table.main.name
}

output "dynamodb_table_arn" {
  description = "DynamoDB table ARN"
  value       = aws_dynamodb_table.main.arn
}

output "secrets_manager_arn" {
  description = "BPC credentials secret ARN"
  value       = aws_secretsmanager_secret.bpc_credentials.arn
}

output "workspace_id" {
  description = "Workspace ID"
  value       = aws_workspaces_workspace.main.id
}

output "workspace_ip" {
  description = "Workspace IP address"
  value       = aws_workspaces_workspace.main.ip_address
}

output "council_credentials_secret_arn" {
  description = "ARN of the secret containing council service AWS credentials"
  value       = aws_secretsmanager_secret.council_credentials.arn
}
