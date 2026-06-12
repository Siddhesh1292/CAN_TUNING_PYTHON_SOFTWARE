#!/bin/bash
# inject-deploy-key.sh
# Run this ONCE after both EC2s are up.
# It generates an SSH key on Jenkins and authorises it on the App server.
#
# Usage:
#   bash scripts/inject-deploy-key.sh \
#       --jenkins-ip  <JENKINS_PUBLIC_IP> \
#       --app-ip      <APP_PUBLIC_IP> \
#       --key         <PATH_TO_YOUR_PEM>
#
set -euo pipefail

JENKINS_IP=""
APP_IP=""
PEM_KEY=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --jenkins-ip) JENKINS_IP="$2"; shift 2 ;;
        --app-ip)     APP_IP="$2";     shift 2 ;;
        --key)        PEM_KEY="$2";    shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

if [[ -z "$JENKINS_IP" || -z "$APP_IP" || -z "$PEM_KEY" ]]; then
    echo "Usage: $0 --jenkins-ip IP --app-ip IP --key path/to/key.pem"
    exit 1
fi

SSH_OPTS="-o StrictHostKeyChecking=no -i $PEM_KEY"

echo "=== Step 1: Generate deploy key on Jenkins EC2 ==="
ssh $SSH_OPTS ubuntu@$JENKINS_IP bash <<'JENK'
if [ ! -f /var/lib/jenkins/.ssh/id_ed25519 ]; then
    sudo mkdir -p /var/lib/jenkins/.ssh
    sudo ssh-keygen -t ed25519 -N "" -f /var/lib/jenkins/.ssh/id_ed25519
    sudo chown -R jenkins:jenkins /var/lib/jenkins/.ssh
    echo "Key generated."
else
    echo "Key already exists — skipping."
fi
cat /var/lib/jenkins/.ssh/id_ed25519.pub
JENK

echo ""
echo "=== Step 2: Fetch public key from Jenkins ==="
JENKINS_PUB_KEY=$(ssh $SSH_OPTS ubuntu@$JENKINS_IP \
    "sudo cat /var/lib/jenkins/.ssh/id_ed25519.pub")
echo "Jenkins public key: $JENKINS_PUB_KEY"

echo ""
echo "=== Step 3: Authorise key on App EC2 ==="
ssh $SSH_OPTS ubuntu@$APP_IP bash <<APPSETUP
sudo mkdir -p /home/deploy/.ssh
echo "$JENKINS_PUB_KEY" | sudo tee -a /home/deploy/.ssh/authorized_keys > /dev/null
sudo chmod 700 /home/deploy/.ssh
sudo chmod 600 /home/deploy/.ssh/authorized_keys
sudo chown -R deploy:deploy /home/deploy/.ssh
echo "Key authorised on app server."
APPSETUP

echo ""
echo "=== Step 4: Verify SSH from Jenkins → App ==="
ssh $SSH_OPTS ubuntu@$JENKINS_IP bash <<VERIFY
sudo -u jenkins ssh -o StrictHostKeyChecking=no deploy@$APP_IP \
    "echo 'SSH connection from Jenkins to App: OK'"
VERIFY

echo ""
echo "========================================================"
echo "  DONE. Now add the private key to Jenkins credentials:"
echo "========================================================"
echo ""
echo "  1. Open http://$JENKINS_IP:8080"
echo "  2. Manage Jenkins → Credentials → Global → Add Credential"
echo "     Kind:        SSH Username with private key"
echo "     ID:          app-server-ssh-key"
echo "     Username:    deploy"
echo "     Private key: Enter directly"
echo ""
echo "  Run this to print the private key:"
echo "  ssh $SSH_OPTS ubuntu@$JENKINS_IP 'sudo cat /var/lib/jenkins/.ssh/id_ed25519'"
echo ""
echo "  3. Also add a Secret Text credential:"
echo "     ID:    app-server-ip"
echo "     Value: $APP_IP"
echo "========================================================"
