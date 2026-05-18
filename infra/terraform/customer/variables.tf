variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "customer_name" {
  description = "Short customer slug — no spaces, lowercase (e.g. acme)"
  type        = string
}

variable "customer_full" {
  description = "Full customer display name (e.g. Acme Corporation)"
  type        = string
}

variable "directory_id" {
  description = "Simple AD directory ID (from shared infrastructure)"
  type        = string
  default     = "d-90660c1382"
}

variable "bpc_server_url" {
  description = "Customer BPC server URL"
  type        = string
}

variable "bpc_username" {
  description = "Customer BPC service account username"
  type        = string
}

variable "bpc_password" {
  description = "Customer BPC service account password"
  type        = string
  sensitive   = true
}

variable "bpc_environment" {
  description = "Customer BPC Environment (AppSet) name"
  type        = string
}

variable "dynamodb_table" {
  description = "Shared DynamoDB table name"
  type        = string
  default     = "darwin-workbench-prod"
}

variable "council_secret_arn" {
  description = "ARN of the council service AWS credentials secret"
  type        = string
  default     = ""
}
