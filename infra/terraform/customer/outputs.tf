output "bpc_secret_arn" {
  description = "ARN of the customer BPC credentials secret"
  value       = aws_secretsmanager_secret.customer_bpc.arn
}

output "customer_name" {
  description = "Customer slug"
  value       = var.customer_name
}
