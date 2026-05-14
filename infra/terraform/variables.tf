variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Project name prefix for all resources"
  type        = string
  default     = "darwin-workbench"
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "prod"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.10.0.0/16"
}

variable "simple_ad_name" {
  description = "Fully qualified domain name for Simple AD"
  type        = string
  default     = "darwin.workbench.local"
}

variable "simple_ad_short_name" {
  description = "NetBIOS name for Simple AD"
  type        = string
  default     = "DARWIN"
}

variable "simple_ad_password" {
  description = "Administrator password for Simple AD"
  type        = string
  sensitive   = true
}

variable "workspace_username" {
  description = "Username for the initial Workspace"
  type        = string
  default     = "darwin-user"
}

variable "bpc_server_url" {
  description = "BPC server URL stored in Secrets Manager"
  type        = string
}

variable "bpc_username" {
  description = "BPC service account username"
  type        = string
}

variable "bpc_password" {
  description = "BPC service account password"
  type        = string
  sensitive   = true
}

variable "bpc_client_id" {
  description = "BPC client ID"
  type        = string
  default     = "100"
}

variable "anthropic_api_key" {
  description = "Anthropic API key (used as fallback if Bedrock is unavailable)"
  type        = string
  sensitive   = true
  default     = ""
}
