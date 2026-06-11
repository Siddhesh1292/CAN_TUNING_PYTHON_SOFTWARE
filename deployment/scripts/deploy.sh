#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# deploy.sh
# Run this on your EC2 instance after Terraform creates it.
# Usage:
#   scp -i your-key.pem deploy.sh ubuntu@<EC2_IP>:~/
#   ssh -i your-key.pem ubuntu@<EC2_IP>
#   bash deploy.sh
#
# What it does:
#   1. Installs system packages (Python, Nginx, Certbot)
#   2. Clones your repo and sets up a Python virtualenv
#   3. Installs the app as a systemd service (auto-restarts on crash/reboot)
#   4. Configures Nginx as a reverse proxy
#   5. Obtains a Let's Encrypt TLS certificate via Certbot
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── EDIT THESE ────────────────────────────────────────────────────────────────
REPO_URL="https://github.com/YOUR_USERNAME/YOUR_REPO.git"   # your git repo URL
APP_DOMAIN="tuner.yourdomain.com"                           # your full subdomain
CERTBOT_EMAIL="you@yourdomain.com"                          # for Let's Encrypt alerts
APP_DIR="/home/ubuntu/can-tuner"
# ─────────────────────────────────────────────────────────────────────────────

echo "=== [1/7] System packages ==="
sudo apt-get update -y
sudo apt-get install -y \
    python3 python3-pip python3-venv \
    nginx certbot python3-certbot-nginx \
    git

echo "=== [2/7] Clone repo ==="
if [ -d "$APP_DIR" ]; then
    echo "Repo already exists — pulling latest..."
    cd "$APP_DIR" && git pull
else
    git clone "$REPO_URL" "$APP_DIR"
fi

echo "=== [3/7] Python virtualenv + dependencies ==="
cd "$APP_DIR"
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install flask gunicorn pyserial openpyxl

echo "=== [4/7] Log directory ==="
sudo mkdir -p /var/log/can-tuner
sudo chown ubuntu:ubuntu /var/log/can-tuner

echo "=== [5/7] Systemd service ==="
sudo cp deployment/systemd/can-tuner.service /etc/systemd/system/can-tuner.service
sudo systemctl daemon-reload
sudo systemctl enable can-tuner
sudo systemctl restart can-tuner
echo "Flask service status:"
sudo systemctl status can-tuner --no-pager

echo "=== [6/7] Nginx config ==="
# Replace placeholder domain in nginx.conf
sed "s/tuner.yourdomain.com/${APP_DOMAIN}/g" \
    deployment/nginx/nginx.conf | sudo tee /etc/nginx/nginx.conf > /dev/null
sudo nginx -t
sudo systemctl restart nginx
sudo systemctl enable nginx

echo "=== [7/7] TLS certificate (Let's Encrypt / Certbot) ==="
# Certbot automatically edits nginx.conf to add ssl_certificate lines
sudo certbot --nginx \
    -d "$APP_DOMAIN" \
    --non-interactive \
    --agree-tos \
    --email "$CERTBOT_EMAIL" \
    --redirect

echo ""
echo "======================================"
echo "  Deploy complete!"
echo "  App running at: https://${APP_DOMAIN}"
echo "  Health check:   https://${APP_DOMAIN}/health"
echo ""
echo "  Useful commands:"
echo "    sudo systemctl status can-tuner    # check Flask"
echo "    sudo journalctl -u can-tuner -f    # live Flask logs"
echo "    sudo systemctl status nginx        # check Nginx"
echo "    sudo tail -f /var/log/nginx/error.log"
echo "======================================"
