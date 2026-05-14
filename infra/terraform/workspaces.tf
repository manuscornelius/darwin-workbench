# Register the directory with Workspaces
resource "aws_workspaces_directory" "main" {
  directory_id = aws_directory_service_directory.simple_ad.id
  subnet_ids   = [
    aws_subnet.public_a.id,
    aws_subnet.public_b.id,
  ]

  workspace_creation_properties {
    enable_internet_access              = true
    enable_maintenance_mode             = true
    user_enabled_as_local_administrator = true
  }

  depends_on = [
    aws_internet_gateway.main,
  ]

  tags = {
    Project = var.project
  }
}

# Performance bundle lookup
data "aws_workspaces_bundle" "performance" {
  bundle_id = "wsb-gm4d5tx2v"  # Performance | Windows 10 | 2 vCPU | 8GB RAM
}

# Initial Workspace for the product
resource "aws_workspaces_workspace" "main" {
  directory_id = aws_workspaces_directory.main.id
  bundle_id    = data.aws_workspaces_bundle.performance.id
  user_name    = var.workspace_username

  workspace_properties {
    running_mode                              = "AUTO_STOP"
    running_mode_auto_stop_timeout_in_minutes = 60
    root_volume_size_gib                      = 80
    user_volume_size_gib                      = 50
    compute_type_name                         = "PERFORMANCE"
  }

  tags = {
    Project     = var.project
    Environment = var.environment
  }

  depends_on = [aws_workspaces_directory.main]
}
