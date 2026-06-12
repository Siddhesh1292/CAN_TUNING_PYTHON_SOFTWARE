variable "project_name"          {}
variable "subnet_id"             {}
variable "jenkins_sg_id"         {}
variable "app_sg_id"             {}
variable "ec2_key_pair_name"     {}
variable "jenkins_instance_type" {}
variable "app_instance_type"     {}
variable "app_port"              {}

# Latest Ubuntu 22.04 LTS in us-east-2
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"]  # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# ── Jenkins EC2 ───────────────────────────────────────────────────────────────
resource "aws_instance" "jenkins" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.jenkins_instance_type
  key_name               = var.ec2_key_pair_name
  subnet_id              = var.subnet_id
  vpc_security_group_ids = [var.jenkins_sg_id]

  root_block_device {
    volume_type           = "gp3"
    volume_size           = 20    # GB — enough for Jenkins + Docker cache
    delete_on_termination = true
    encrypted             = true
  }

  user_data = base64encode(templatefile("${path.module}/jenkins-init.sh", {
    app_port = var.app_port
  }))

  tags = { Name = "${var.project_name}-jenkins" }
}

# ── App EC2 ───────────────────────────────────────────────────────────────────
resource "aws_instance" "app" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.app_instance_type
  key_name               = var.ec2_key_pair_name
  subnet_id              = var.subnet_id
  vpc_security_group_ids = [var.app_sg_id]

  root_block_device {
    volume_type           = "gp3"
    volume_size           = 15    # GB — app + Docker image
    delete_on_termination = true
    encrypted             = true
  }

  user_data = base64encode(templatefile("${path.module}/app-init.sh", {
    app_port = var.app_port
  }))

  tags = { Name = "${var.project_name}-app" }
}

# ── Elastic IP for app EC2 (so DNS stays stable across reboots) ───────────────
resource "aws_eip" "app" {
  instance = aws_instance.app.id
  domain   = "vpc"
  tags     = { Name = "${var.project_name}-app-eip" }
}

# ── Outputs ───────────────────────────────────────────────────────────────────
output "jenkins_public_ip" { value = aws_instance.jenkins.public_ip }
output "app_eip"           { value = aws_eip.app.public_ip }
output "jenkins_instance_id" { value = aws_instance.jenkins.id }
output "app_instance_id"     { value = aws_instance.app.id }
