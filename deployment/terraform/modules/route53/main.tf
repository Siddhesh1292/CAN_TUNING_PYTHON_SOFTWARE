# ── Route 53 + ACM Module ─────────────────────────────────────────────────────

variable "domain_name"   {}
variable "app_subdomain" {}
variable "ec2_public_ip" {}

# Look up the existing hosted zone (must be created in AWS Console first)
data "aws_route53_zone" "main" {
  name         = var.domain_name
  private_zone = false
}

# ── A record → EC2 Elastic IP ─────────────────────────────────────────────────
resource "aws_route53_record" "app" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = "${var.app_subdomain}.${var.domain_name}"
  type    = "A"
  ttl     = 300
  records = [var.ec2_public_ip]
}

# ── ACM Certificate ────────────────────────────────────────────────────────────
# Note: Certbot on the EC2 handles TLS directly (simpler than ACM for a single VM).
# This resource is kept here if you later want ACM for an ALB in front of the EC2.
# For the basic EC2 setup, Certbot (Let's Encrypt) is used instead — see deploy.sh.

# ── Route 53 Health Check ──────────────────────────────────────────────────────
resource "aws_route53_health_check" "app" {
  fqdn              = "${var.app_subdomain}.${var.domain_name}"
  port              = 443
  type              = "HTTPS"
  resource_path     = "/health"
  failure_threshold = 3
  request_interval  = 30

  tags = { Name = "can-tuner-health-check" }
}

output "app_fqdn"         { value = aws_route53_record.app.fqdn }
output "health_check_id"  { value = aws_route53_health_check.app.id }
