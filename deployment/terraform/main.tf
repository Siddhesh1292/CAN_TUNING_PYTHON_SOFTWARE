terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = var.tags
  }
}

# ── Networking ─────────────────────────────────────────────────────────────────
module "vpc" {
  source            = "./modules/vpc"
  project_name      = var.project_name
  vpc_cidr          = var.vpc_cidr
  availability_zone = var.availability_zone
}

# ── Security Groups ────────────────────────────────────────────────────────────
module "sg" {
  source       = "./modules/sg"
  project_name = var.project_name
  vpc_id       = module.vpc.vpc_id
  app_port     = var.app_port
}

# ── EC2 Instances ──────────────────────────────────────────────────────────────
module "ec2" {
  source                = "./modules/ec2"
  project_name          = var.project_name
  subnet_id             = module.vpc.public_subnet_id
  jenkins_sg_id         = module.sg.jenkins_sg_id
  app_sg_id             = module.sg.app_sg_id
  ec2_key_pair_name     = var.ec2_key_pair_name
  jenkins_instance_type = var.jenkins_instance_type
  app_instance_type     = var.app_instance_type
  app_port              = var.app_port
}

# ── Route 53 DNS (A record → app EC2 Elastic IP) ──────────────────────────────
module "route53" {
  source        = "./modules/route53"
  domain_name   = var.domain_name
  app_subdomain = var.app_subdomain
  app_eip       = module.ec2.app_eip
}

# ── Outputs ────────────────────────────────────────────────────────────────────
output "jenkins_public_ip" {
  value       = module.ec2.jenkins_public_ip
  description = "SSH / UI access: http://<jenkins_public_ip>:8080"
}

output "app_public_ip" {
  value       = module.ec2.app_eip
  description = "App Elastic IP — also registered in Route 53"
}

output "app_url" {
  value       = "http://${var.app_subdomain}.${var.domain_name}"
  description = "Public URL of the CAN Tuner dashboard"
}

output "ssh_jenkins" {
  value = "ssh -i <your-key>.pem ubuntu@${module.ec2.jenkins_public_ip}"
}

output "ssh_app" {
  value = "ssh -i <your-key>.pem ubuntu@${module.ec2.app_eip}"
}
