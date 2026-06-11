terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Remote state — create this S3 bucket manually before first apply
  backend "s3" {
    bucket         = "can-tuner-terraform-state"   # change to your bucket name
    key            = "prod/terraform.tfstate"
    region         = "ap-south-1"
    encrypt        = true
    dynamodb_table = "can-tuner-tf-lock"
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = var.tags
  }
}

# ── EC2 instance (Flask + Nginx run here directly) ─────────────────────────────
module "ec2" {
  source = "./modules/ec2"

  project_name      = var.project_name
  environment       = var.environment
  aws_region        = var.aws_region
  instance_type     = var.instance_type
  key_pair_name     = var.key_pair_name
  allowed_ssh_cidrs = var.allowed_ssh_cidrs
}

# ── Route 53 + ACM certificate ─────────────────────────────────────────────────
module "route53" {
  source = "./modules/route53"

  domain_name   = var.domain_name
  app_subdomain = var.app_subdomain
  ec2_public_ip = module.ec2.public_ip
}

# ── Outputs ────────────────────────────────────────────────────────────────────
output "ec2_public_ip" {
  description = "Public IP of the EC2 instance"
  value       = module.ec2.public_ip
}

output "ec2_instance_id" {
  description = "EC2 instance ID"
  value       = module.ec2.instance_id
}

output "app_url" {
  description = "Public URL of the deployed app"
  value       = "https://${var.app_subdomain}.${var.domain_name}"
}

output "ssh_command" {
  description = "SSH command to connect to the EC2 instance"
  value       = "ssh -i ${var.key_pair_name}.pem ubuntu@${module.ec2.public_ip}"
}
