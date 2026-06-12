# CAN Tuner — Lean Cloud Deployment
### AWS Ohio (us-east-2) · 2× t3.small EC2 · Jenkins CI/CD · Docker · Route 53

No ECS. No ECR. No Fargate. No NAT Gateway. Just two cheap EC2s and Docker.

---

## Architecture

```
Developer
    │  git push main
    ▼
┌─────────────────────────────────────┐
│  Jenkins EC2  (t3.small)            │
│  ─ builds Docker image              │
│  ─ saves → .tar                     │
│  ─ SCP tar to App EC2               │
│  ─ SSH: docker load + restart       │
└─────────────────────────────────────┘
                  │ SSH + SCP
                  ▼
┌─────────────────────────────────────┐     Route 53 A-record
│  App EC2  (t3.small)                │◄────────────────────── tuner.yourdomain.com
│  ─ nginx :80 → Flask :5000          │     (Elastic IP)
│  ─ Docker container: can-tuner      │
└─────────────────────────────────────┘
```

**Single AZ · Single public subnet · No NAT Gateway · Elastic IP for stable DNS**

---

## Cost Estimate (us-east-2, Ohio)

| Resource | Config | $/month |
|----------|--------|---------|
| Jenkins EC2 | t3.small, 24/7 | ~$15 |
| App EC2 | t3.small, 24/7 | ~$15 |
| EBS volumes | 20 GB + 15 GB gp3 | ~$3 |
| Elastic IP | 1× (free while attached) | $0 |
| Route 53 | 1 zone + queries | ~$1 |
| Data transfer | ~10 GB/month | ~$1 |
| **Total** | | **~$35/month** |

> **vs previous architecture (~$135/month) — saves ~$100/month**

### Can I use t3.small instead of t3.medium?
**Yes.** t3.small (2 vCPU / 2 GB RAM) is sufficient because:
- Jenkins only builds one pipeline at a time (no parallelism needed)
- The Flask app is lightweight — 2 Gunicorn workers use ~200 MB RAM
- Docker build cache keeps subsequent builds fast even on 2 GB

Upgrade to t3.medium (~$30/mo each) only if Jenkins slows down on large builds.

---

## Prerequisites

- [ ] AWS CLI v2 installed (`aws configure` with your IAM credentials)
- [ ] Terraform >= 1.6 installed
- [ ] An EC2 Key Pair created in **us-east-2** (Ohio)
- [ ] A domain with its Hosted Zone in Route 53

---

## File Structure

```
your-repo/
├── app.py
├── waveshare_can.py
├── can_tuner3.py
├── templates/index.html
├── static/{styles.css,app.js}
├── tests/                        ← put pytest tests here
│
└── deployment/
    ├── docker/
    │   ├── Dockerfile
    │   └── requirements.txt
    ├── nginx/
    │   └── can-tuner.conf
    ├── jenkins/
    │   └── Jenkinsfile
    ├── scripts/
    │   └── inject-deploy-key.sh
    └── terraform/
        ├── main.tf
        ├── variables.tf
        ├── terraform.tfvars.example
        └── modules/
            ├── vpc/main.tf
            ├── sg/main.tf
            ├── ec2/main.tf
            │   ├── jenkins-init.sh   (user-data)
            │   └── app-init.sh       (user-data)
            └── route53/main.tf
```

---

## Step 0 — Prep your repo

### Add the /health endpoint to app.py
The pipeline health check requires this route. Add it to `app.py`:

```python
@app.get("/health")
def health():
    return {"status": "ok"}, 200
```

### Move static files into correct paths
```bash
mkdir -p templates static tests
mv index.html templates/
mv styles.css app.js static/
cp deployment/docker/requirements.txt .
```

---

## Step 1 — Bootstrap Terraform state

Run once on your local machine:

```bash
# Create S3 bucket for state
aws s3api create-bucket \
  --bucket can-tuner-terraform-state-ohio \
  --region us-east-2 \
  --create-bucket-configuration LocationConstraint=us-east-2

aws s3api put-bucket-versioning \
  --bucket can-tuner-terraform-state-ohio \
  --versioning-configuration Status=Enabled

# Create DynamoDB table for locking
aws dynamodb create-table \
  --table-name can-tuner-tf-lock \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region us-east-2
```

---

## Step 2 — Provision EC2s with Terraform

```bash
cd deployment/terraform

# Fill in your values
cp terraform.tfvars.example terraform.tfvars
nano terraform.tfvars
# Set: domain_name, ec2_key_pair_name

# Init + apply
terraform init
terraform plan
terraform apply
```

Terraform creates in ~3 minutes:
- VPC, public subnet, Internet Gateway, route table
- Security groups for Jenkins and App
- Jenkins EC2 (t3.small) — auto-installs Java, Jenkins, Docker, AWS CLI via user-data
- App EC2 (t3.small) — auto-installs Docker, nginx via user-data
- Elastic IP attached to App EC2
- Route 53 A-record: `tuner.yourdomain.com → <elastic-ip>`

```bash
# Save these outputs — you'll need them
terraform output
# jenkins_public_ip = "3.x.x.x"
# app_public_ip     = "18.x.x.x"
# ssh_jenkins       = "ssh -i your-key.pem ubuntu@3.x.x.x"
# ssh_app           = "ssh -i your-key.pem ubuntu@18.x.x.x"
```

### Wait for user-data to complete (~3 min)
```bash
# Watch Jenkins init log
ssh -i your-key.pem ubuntu@<JENKINS_IP> "tail -f /var/log/jenkins-init.log"

# Watch App init log
ssh -i your-key.pem ubuntu@<APP_IP> "tail -f /var/log/app-init.log"
```

---

## Step 3 — Wire Jenkins → App EC2 (SSH key)

This script generates an SSH key on Jenkins and installs it on the App server:

```bash
bash deployment/scripts/inject-deploy-key.sh \
    --jenkins-ip <JENKINS_IP> \
    --app-ip     <APP_IP> \
    --key        ~/.ssh/your-key.pem
```

The script prints the private key and exact steps to add it to Jenkins credentials.

---

## Step 4 — Configure Jenkins

### Unlock Jenkins
Open `http://<JENKINS_IP>:8080`

Get the initial admin password:
```bash
ssh -i your-key.pem ubuntu@<JENKINS_IP> \
    "sudo cat /var/lib/jenkins/secrets/initialAdminPassword"
```

### Install Plugins
Choose **Install suggested plugins**, then additionally install:

| Plugin | Why |
|--------|-----|
| Blue Ocean | Better pipeline visualisation |
| SSH Agent | For SSH credentials in pipeline |
| AnsiColor | Coloured console output |
| Slack Notification | Optional deploy notifications |

### Add Credentials
**Manage Jenkins → Credentials → System → Global → Add Credential**

| Credential ID | Kind | Value |
|---------------|------|-------|
| `app-server-ssh-key` | SSH Username with private key | Username: `deploy`, paste the private key from Step 3 |
| `app-server-ip` | Secret text | The App EC2 Elastic IP |

### Create the Pipeline Job
1. **New Item → Pipeline → Name:** `can-tuner`
2. **Build Triggers:** ✅ `GitHub hook trigger for GITScm polling`
3. **Pipeline → Definition:** `Pipeline script from SCM`
4. **SCM:** Git
5. **Repository URL:** your GitHub/GitLab URL
6. **Branch:** `*/main`
7. **Script Path:** `deployment/jenkins/Jenkinsfile`
8. Save → **Build Now**

---

## Step 5 — Set up GitHub Webhook

In your GitHub repo: **Settings → Webhooks → Add webhook**

```
Payload URL:  http://<JENKINS_IP>:8080/github-webhook/
Content type: application/json
Events:       Just the push event
```

Now every `git push origin main` triggers the pipeline automatically.

---

## Step 6 — Verify Deployment

```bash
# App health via nginx
curl http://<APP_IP>/health
# ok

# App health via domain (after DNS propagates ~5 min)
curl http://tuner.yourdomain.com/health
# ok

# View live Docker logs on app server
ssh -i your-key.pem ubuntu@<APP_IP> \
    "docker logs -f can-tuner"

# Check nginx
ssh -i your-key.pem ubuntu@<APP_IP> \
    "sudo nginx -t && sudo systemctl status nginx"
```

Open `http://tuner.yourdomain.com` — the CAN Tuner dashboard should load.

---

## Pipeline Stages at a Glance

```
[Checkout] → [Lint] → [Test] → [Build Image] → [Export .tar]
    → [SCP to App EC2] → [SSH: docker load + run] → [Health Check] → [Cleanup]
```

On failure at any stage: Jenkins marks the build red, old container keeps running.

---

## Day-2 Operations

### Deploy manually
```bash
# In Jenkins UI → can-tuner → Build Now
```

### Rollback to previous build
```bash
# On app EC2 — previous tars are kept in /home/deploy/images/
ssh -i your-key.pem ubuntu@<APP_IP>

# List available images
ls -lth /home/deploy/images/

# Load an older build
docker load -i /home/deploy/images/can-tuner-<OLD_SHA>.tar
docker stop can-tuner
docker run -d --name can-tuner --restart unless-stopped \
    -p 5000:5000 can-tuner:latest
```

### View logs
```bash
# App container logs
ssh -i your-key.pem ubuntu@<APP_IP> "docker logs --tail 100 can-tuner"

# nginx access logs
ssh -i your-key.pem ubuntu@<APP_IP> "sudo tail -f /var/log/nginx/access.log"

# Jenkins build logs
# Jenkins UI → can-tuner → Build #N → Console Output
```

### Stop/start EC2s to save money
```bash
# When not in use (e.g. nights/weekends)
aws ec2 stop-instances --instance-ids <JENKINS_ID> <APP_ID> --region us-east-2

# Resume work
aws ec2 start-instances --instance-ids <JENKINS_ID> <APP_ID> --region us-east-2
# NOTE: Jenkins IP changes on restart — App IP stays (Elastic IP)
```

### Destroy everything
```bash
cd deployment/terraform
terraform destroy
# Also manually delete: S3 bucket, DynamoDB table
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Jenkins can't SSH to App | Re-run `inject-deploy-key.sh`; check `app-server-ssh-key` credential |
| Health check fails (HTTP 000) | Container didn't start — `docker logs can-tuner` on App EC2 |
| nginx 502 Bad Gateway | Flask not running — `docker ps` on App EC2 |
| DNS not resolving | Check Route 53 A-record points to correct Elastic IP; wait 5 min |
| `docker: permission denied` on Jenkins | `sudo usermod -aG docker jenkins && sudo systemctl restart jenkins` |
| t3.small running out of memory during build | Add 1 GB swap: `sudo fallocate -l 1G /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile` |

### Add swap (recommended for t3.small Jenkins)
```bash
ssh -i your-key.pem ubuntu@<JENKINS_IP>
sudo fallocate -l 1G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h   # should show 1 GB swap
```

---

*CAN Tuner · AWS us-east-2 (Ohio) · t3.small × 2 · ~$35/month*
