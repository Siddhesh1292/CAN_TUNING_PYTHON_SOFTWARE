# ── Global variables ──────────────────────────────────────────────────────────

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-2"   # Ohio
}

variable "environment" {
  type    = string
  default = "prod"
}

variable "project_name" {
  type    = string
  default = "can-tuner"
}

variable "domain_name" {
  description = "Root domain managed in Route 53 (e.g. example.com)"
  type        = string
}

variable "app_subdomain" {
  description = "Subdomain for the app (results in app_subdomain.domain_name)"
  type        = string
  default     = "tuner"
}

variable "vpc_cidr" {
  type    = string
  default = "10.0.0.0/16"
}

# Single AZ — cheap
variable "availability_zone" {
  type    = string
  default = "us-east-2a"
}

variable "ec2_key_pair_name" {
  description = "Name of an existing EC2 Key Pair for SSH access"
  type        = string
}

# t3.small = 2 vCPU / 2 GB RAM — works fine for both Jenkins and app
variable "jenkins_instance_type" {
  type    = string
  default = "t3.small"
}

variable "app_instance_type" {
  type    = string
  default = "t3.small"
}

variable "app_port" {
  type    = number
  default = 5000
}

variable "certificate_arn" {
  description = "ACM certificate ARN (us-east-2) for HTTPS on the ALB"
  type        = string
}

variable "tags" {
  type = map(string)
  default = {
    Project   = "CAN-Tuner"
    ManagedBy = "Terraform"
  }
}
