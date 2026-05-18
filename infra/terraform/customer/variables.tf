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

