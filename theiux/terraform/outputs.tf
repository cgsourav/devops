output "instance_id" {
  value = aws_instance.app.id
}

output "public_ip" {
  value = aws_eip.app.public_ip
}

output "security_group_id" {
  value = aws_security_group.app.id
}

output "ecr_repository_url" {
  value = aws_ecr_repository.frappe.repository_url
}

output "artifact_bucket" {
  value = aws_s3_bucket.artifacts.bucket
}

output "cloudwatch_log_group" {
  value = aws_cloudwatch_log_group.app.name
}

output "route53_record_fqdn" {
  value = local.use_route53 ? aws_route53_record.app[0].fqdn : ""
}

output "ssm_parameter_path" {
  value = local.ssm_parameter_path
}

output "aws_region" {
  value = var.aws_region
}

output "deploy_path" {
  value = var.deploy_path
}
