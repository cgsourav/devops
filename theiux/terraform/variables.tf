variable "project_name" {
  description = "Project prefix for resources."
  type        = string
  default     = "theiux"
}

variable "environment" {
  description = "Environment name."
  type        = string
  default     = "prod"
}

variable "aws_region" {
  description = "AWS region."
  type        = string
}

variable "instance_type" {
  description = "EC2 instance type."
  type        = string
  default     = "t3.small"
}

variable "root_volume_size_gb" {
  description = "Root EBS volume size."
  type        = number
  default     = 40
}

variable "route53_zone_id" {
  description = "Optional Route53 hosted zone ID."
  type        = string
  default     = ""
}

variable "root_domain" {
  description = "Optional root domain."
  type        = string
  default     = ""
}

variable "subdomain" {
  description = "Optional subdomain. Use '@' to map apex."
  type        = string
  default     = "@"
}

variable "repo_url" {
  description = "Git repository URL cloned by instance bootstrap."
  type        = string
}

variable "repo_ref" {
  description = "Git branch/tag to checkout."
  type        = string
  default     = "main"
}

variable "deploy_path" {
  description = "Path on EC2 where project will run."
  type        = string
  default     = "/opt/theiux"
}

variable "app_user" {
  description = "Host OS user for deployment."
  type        = string
  default     = "ubuntu"
}

variable "allowed_http_cidr_blocks" {
  description = "Allowed CIDRs for HTTP/HTTPS."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "ecr_force_delete" {
  description = "Force delete ECR repo when destroying."
  type        = bool
  default     = false
}

variable "frappe_image_repo_name" {
  description = "ECR repository name for frappe image."
  type        = string
  default     = "theiux-frappe"
}
