variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "ap-south-1"   # Mumbai — closest to Pune
}

variable "environment" {
  description = "Deployment environment (prod / staging)"
  type        = string
  default     = "prod"
}

variable "project_name" {
  description = "Short name used to prefix all resource names"
  type        = string
  default     = "can-tuner"
}

variable "domain_name" {
  description = "Root domain managed in Route 53 (must already exist as a Hosted Zone)"
  type        = string
  # e.g. "example.com"
}

variable "app_subdomain" {
  description = "Subdomain for the app"
  type        = string
  default     = "tuner"
  # Results in tuner.example.com
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "t3.small"   # 2 vCPU, 2 GB RAM — plenty for Flask + Nginx
}

variable "key_pair_name" {
  description = "Name of an existing EC2 key pair for SSH access"
  type        = string
  # Create one in EC2 Console → Key Pairs, then put the name here
}

variable "allowed_ssh_cidrs" {
  description = "CIDR blocks allowed to SSH into the EC2 instance (restrict to your IP)"
  type        = list(string)
  default     = ["0.0.0.0/0"]   # Change to your IP, e.g. ["203.0.113.42/32"]
}

variable "tags" {
  description = "Tags applied to all resources"
  type        = map(string)
  default = {
    Project     = "CAN-Tuner"
    ManagedBy   = "Terraform"
    Environment = "prod"
  }
}
