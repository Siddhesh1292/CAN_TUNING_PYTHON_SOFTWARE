#!/bin/bash
# jenkins-init.sh — runs once on first boot via EC2 user-data
set -euo pipefail
exec > /var/log/jenkins-init.log 2>&1

echo "=== [1/5] System update ==="
apt-get update -y
apt-get install -y curl gnupg lsb-release ca-certificates git unzip jq python3 python3-pip

echo "=== [2/5] Java 17 ==="
apt-get install -y openjdk-17-jdk
java -version

echo "=== [3/5] Jenkins LTS ==="
curl -fsSL https://pkg.jenkins.io/debian-stable/jenkins.io-2023.key \
    | tee /usr/share/keyrings/jenkins-keyring.asc > /dev/null
echo "deb [signed-by=/usr/share/keyrings/jenkins-keyring.asc] \
    https://pkg.jenkins.io/debian-stable binary/" \
    | tee /etc/apt/sources.list.d/jenkins.list > /dev/null
apt-get update -y
apt-get install -y jenkins
systemctl enable --now jenkins

echo "=== [4/5] Docker CE ==="
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
usermod -aG docker jenkins
usermod -aG docker ubuntu

echo "=== [5/5] AWS CLI v2 ==="
curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip
unzip -q /tmp/awscliv2.zip -d /tmp/
/tmp/aws/install
rm -rf /tmp/aws /tmp/awscliv2.zip

# Restart Jenkins so it picks up the docker group
systemctl restart jenkins

echo "=== Jenkins init complete ==="
echo "Admin password: $(cat /var/lib/jenkins/secrets/initialAdminPassword)"
