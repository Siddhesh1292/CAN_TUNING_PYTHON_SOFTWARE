#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# update.sh
# Run this on the EC2 whenever you push new code and want to redeploy.
# Usage (from your local machine):
#   ssh -i your-key.pem ubuntu@<EC2_IP> "bash ~/can-tuner/deployment/scripts/update.sh"
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

APP_DIR="/home/ubuntu/can-tuner"

echo "=== Pulling latest code ==="
cd "$APP_DIR"
git pull

echo "=== Installing any new dependencies ==="
venv/bin/pip install --quiet flask gunicorn pyserial openpyxl

echo "=== Restarting Flask service ==="
sudo systemctl restart can-tuner
sleep 2
sudo systemctl status can-tuner --no-pager

echo "=== Done. App restarted with latest code. ==="
