variable "domain_name"   {}
variable "app_subdomain" {}
variable "app_eip"       {}

data "aws_route53_zone" "main" {
  name         = var.domain_name
  private_zone = false
}

resource "aws_route53_record" "app" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = "${var.app_subdomain}.${var.domain_name}"
  type    = "A"
  ttl     = 300
  records = [var.app_eip]
}

output "app_fqdn" { value = aws_route53_record.app.fqdn }
