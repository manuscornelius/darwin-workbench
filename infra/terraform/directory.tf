# Simple AD — required by AWS Workspaces
resource "aws_directory_service_directory" "simple_ad" {
  name       = var.simple_ad_name
  short_name = var.simple_ad_short_name
  password   = var.simple_ad_password
  size       = "Small"
  type       = "SimpleAD"

  vpc_settings {
    vpc_id     = aws_vpc.main.id
    subnet_ids = [
      aws_subnet.public_a.id,
      aws_subnet.public_b.id,
    ]
  }

  tags = {
    Name    = "${var.project}-simple-ad"
    Project = var.project
  }
}
