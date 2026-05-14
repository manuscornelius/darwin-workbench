# BPC credentials stored in Secrets Manager
resource "aws_secretsmanager_secret" "bpc_credentials" {
  name        = "${var.project}/bpc-credentials"
  description = "SAP BPC service account credentials for Darwin Workbench"

  tags = {
    Project = var.project
  }
}

resource "aws_secretsmanager_secret_version" "bpc_credentials" {
  secret_id = aws_secretsmanager_secret.bpc_credentials.id

  secret_string = jsonencode({
    server_url  = var.bpc_server_url
    username    = var.bpc_username
    password    = var.bpc_password
    client_id   = var.bpc_client_id
  })
}
