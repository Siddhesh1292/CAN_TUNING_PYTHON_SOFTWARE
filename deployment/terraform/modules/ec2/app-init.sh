#!/bin/bash
# app-init.sh — runs once on first boot via EC2 user-data
set -euo pipefail
exec > /var/log/app-init.log 2>&1

APP_PORT=${app_port}

echo "=== [1/4] System update ==="
apt-get update -y
apt-get install -y curl ca-certificates gnupg lsb-release nginx

echo "=== [2/4] Docker CE ==="
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
    https://download.docker.com/linux/ubuntu \
    $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    | tee /etc/apt/sources.list.d/docker.list > /dev/null
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin
systemctl enable --now docker
usermod -aG docker ubuntu

echo "=== [3/4] nginx reverse proxy ==="
cat > /etc/nginx/sites-available/can-tuner <<'NGINX'
server {
    listen 80;
    server_name _;

    location /health {
        access_log off;
        return 200 "ok\n";
        add_header Content-Type text/plain;
    }

    location / {
        proxy_pass         http://127.0.0.1:APP_PORT_PLACEHOLDER;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_read_timeout 120s;
    }
}
NGINX

sed -i "s/APP_PORT_PLACEHOLDER/$APP_PORT/" /etc/nginx/sites-available/can-tuner
ln -sf /etc/nginx/sites-available/can-tuner /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable --now nginx

echo "=== [4/4] Create deploy user for Jenkins SSH ==="
# Jenkins will SSH in as 'deploy' to run docker commands
useradd -m -s /bin/bash deploy
usermod -aG docker deploy
mkdir -p /home/deploy/.ssh
chmod 700 /home/deploy/.ssh
# Jenkins public key is injected by the deploy script — see README
chown -R deploy:deploy /home/deploy/.ssh

echo "=== App server init complete ==="
