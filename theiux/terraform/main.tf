data "aws_caller_identity" "current" {}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }
}

locals {
  name_prefix        = "${var.project_name}-${var.environment}"
  s3_bucket_name     = "${var.project_name}-${var.environment}-${data.aws_caller_identity.current.account_id}"
  fqdn               = var.root_domain == "" ? "" : (var.subdomain == "@" ? var.root_domain : "${var.subdomain}.${var.root_domain}")
  use_route53        = var.route53_zone_id != "" && var.root_domain != ""
  ssm_parameter_path = "/${var.project_name}/${var.environment}"
}

resource "aws_ecr_repository" "frappe" {
  name                 = var.frappe_image_repo_name
  image_tag_mutability = "MUTABLE"
  force_delete         = var.ecr_force_delete
}

resource "aws_s3_bucket" "artifacts" {
  bucket        = local.s3_bucket_name
  force_destroy = true
}

resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_security_group" "app" {
  name        = "${local.name_prefix}-sg"
  description = "HTTP/HTTPS only for theiux"
  vpc_id      = data.aws_vpc.default.id

  dynamic "ingress" {
    for_each = var.allowed_http_cidr_blocks
    content {
      from_port   = 80
      to_port     = 80
      protocol    = "tcp"
      cidr_blocks = [ingress.value]
    }
  }

  dynamic "ingress" {
    for_each = var.allowed_http_cidr_blocks
    content {
      from_port   = 443
      to_port     = 443
      protocol    = "tcp"
      cidr_blocks = [ingress.value]
    }
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_role" "ec2" {
  name               = "${local.name_prefix}-ec2-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy_attachment" "cw_agent" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

resource "aws_iam_role_policy_attachment" "ecr_read" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

resource "aws_iam_role_policy_attachment" "s3_full" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3FullAccess"
}

resource "aws_iam_role_policy" "ssm_params" {
  name = "${local.name_prefix}-ssm-params"
  role = aws_iam_role.ec2.id
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Action = [
          "ssm:GetParameter",
          "ssm:GetParameters",
          "ssm:GetParametersByPath"
        ],
        Resource = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${local.ssm_parameter_path}/*"
      }
    ]
  })
}

resource "aws_iam_instance_profile" "ec2" {
  name = "${local.name_prefix}-ec2-profile"
  role = aws_iam_role.ec2.name
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/${var.project_name}/${var.environment}/containers"
  retention_in_days = 30
}

resource "aws_instance" "app" {
  ami                         = data.aws_ami.ubuntu.id
  instance_type               = var.instance_type
  subnet_id                   = data.aws_subnets.default.ids[0]
  associate_public_ip_address = true
  iam_instance_profile        = aws_iam_instance_profile.ec2.name
  vpc_security_group_ids      = [aws_security_group.app.id]

  root_block_device {
    volume_size = var.root_volume_size_gb
    volume_type = "gp3"
  }

  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    app_user    = var.app_user
    deploy_path = var.deploy_path
    repo_url    = var.repo_url
    repo_ref    = var.repo_ref
    aws_region  = var.aws_region
  })

  tags = {
    Name        = "${local.name_prefix}-ec2"
    Project     = var.project_name
    Environment = var.environment
  }
}

resource "aws_eip" "app" {
  domain   = "vpc"
  instance = aws_instance.app.id
  tags = {
    Name = "${local.name_prefix}-eip"
  }
}

resource "aws_route53_record" "app" {
  count   = local.use_route53 ? 1 : 0
  zone_id = var.route53_zone_id
  name    = local.fqdn
  type    = "A"
  ttl     = 60
  records = [aws_eip.app.public_ip]
}
