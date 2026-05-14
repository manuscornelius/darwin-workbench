# VPC
resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name        = "${var.project}-vpc"
    Project     = var.project
    Environment = var.environment
  }
}

# Internet Gateway
resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name    = "${var.project}-igw"
    Project = var.project
  }
}

# Public subnets (two AZs — required by Simple AD and Workspaces)
resource "aws_subnet" "public_a" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.10.1.0/24"
  availability_zone_id    = "use1-az4"
  map_public_ip_on_launch = true

  tags = {
    Name    = "${var.project}-public-a"
    Project = var.project
  }
}

resource "aws_subnet" "public_b" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.10.2.0/24"
  availability_zone_id    = "use1-az6"
  map_public_ip_on_launch = true

  tags = {
    Name    = "${var.project}-public-b"
    Project = var.project
  }
}

# Route table
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name    = "${var.project}-rt-public"
    Project = var.project
  }
}

resource "aws_route_table_association" "public_a" {
  subnet_id      = aws_subnet.public_a.id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "public_b" {
  subnet_id      = aws_subnet.public_b.id
  route_table_id = aws_route_table.public.id
}

# Security group for Workspaces
resource "aws_security_group" "workspaces" {
  name        = "${var.project}-workspaces-sg"
  description = "Security group for Darwin Workbench Workspaces"
  vpc_id      = aws_vpc.main.id

  # Allow all outbound (Workspaces needs internet for Bedrock, BPC, updates)
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "${var.project}-workspaces-sg"
    Project = var.project
  }
}
