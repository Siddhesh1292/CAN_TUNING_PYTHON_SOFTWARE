# CAN Tuner Dashboard — Full Cloud Deployment Guide

> AWS ECS Fargate · Jenkins CI/CD · Route 53 · Terraform IaC  
> Region: `ap-south-1` (Mumbai) — closest to Pune

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Important: Serial Port Limitation](#2-important-serial-port-limitation)
3. [Prerequisites](#3-prerequisites)
4. [Repository Structure](#4-repository-structure)
5. [Step 1 — Bootstrap AWS Account](#5-step-1--bootstrap-aws-account)
6. [Step 2 — Launch Jenkins EC2](#6-step-2--launch-jenkins-ec2)
7. [Step 3 — Configure Jenkins](#7-step-3--configure-jenkins)
8. [Step 4 — Provision Infrastructure with Terraform](#8-step-4--provision-infrastructure-with-terraform)
9. [Step 5 — Build & Push First Docker Image](#9-step-5--build--push-first-docker-image)
10. [Step 6 — Create Jenkins Pipeline](#10-step-6--create-jenkins-pipeline)
11. [Step 7 — DNS & HTTPS with Route 53](#11-step-7--dns--https-with-route-53)
12. [Step 8 — Verify End-to-End](#12-step-8--verify-end-to-end)
13. [Day-2 Operations](#13-day-2-operations)
14. [Troubleshooting](#14-troubleshooting)
15. [Cost Estimate](#15-cost-estimate)

---

## 1. Architecture Overview

```
Developer
    │  git push → GitHub/CodeCommit
    │
    ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Jenkins EC2  (t3.medium, ap-south-1)                                │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Pipeline stages:                                            │   │
│  │  Checkout → Lint → Test → Build → Push ECR → Deploy ECS     │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
         │ docker push
         ▼
┌────────────────────┐
│  Amazon ECR        │  ← Docker image registry
└────────────────────┘
         │ image pull
         ▼
┌─────────────────────────────────────────────────────────────┐
│  VPC  10.0.0.0/16                                           │
│                                                             │
│  Public Subnets (1a, 1b)       Private Subnets (1a, 1b)    │
│  ┌───────────────────┐         ┌──────────────────────┐    │
│  │  Application LB   │────────▶│  ECS Fargate Tasks   │    │
│  │  (HTTPS :443)     │         │  Flask app :5000     │    │
│  └───────────────────┘         └──────────────────────┘    │
│           ▲                             │                   │
│           │ A-record alias              │ outbound via NAT  │
└───────────┼─────────────────────────────┼───────────────────┘
            │                             ▼
    Route 53 HostedZone             NAT Gateways
    tuner.yourdomain.com
```

**Traffic flow:**  
User → Route 53 DNS → ALB (HTTPS/TLS termination) → ECS Fargate tasks → Flask app

---

## 2. Important: Serial Port Limitation

Your app uses `pyserial` to talk to CAN/UART hardware through a physical USB port.
**AWS Fargate containers do not have physical USB/serial ports.**

### Production Options

| Option | Description | Complexity |
|--------|-------------|------------|
| **Hybrid (Recommended)** | Flask runs on-prem on a Raspberry Pi or small server connected to the ESC hardware. Only the web UI is reverse-proxied to the cloud. | Low |
| **EC2 + USB over IP** | Run the app on an EC2-like on-prem server, tunnel serial via `ser2net` or `RFC 2217` over a VPN to the cloud instance. | Medium |
| **EC2 (not Fargate)** | Use an EC2 instance with AWS Nitro and pass a USB device via udev rules + EC2 serial console. | High, limited |
| **This guide (Cloud UI only)** | Deploy the web dashboard to ECS. Connect hardware via the UART/CAN endpoint from a local machine that has the device. Works if users have the USB device attached locally. | Minimal change |

> This guide deploys the full app to ECS. For hardware-connected use, run the app
> on a local machine with the USB device and use the deployed version as a
> remote-access mirror / config backup tool.

---

## 3. Prerequisites

### Local machine
- [ ] AWS CLI v2 installed and configured (`aws configure`)
- [ ] Terraform >= 1.6.0
- [ ] Docker Desktop / Docker Engine
- [ ] Git

### AWS Account
- [ ] IAM user with AdministratorAccess (for initial setup; lock down after)
- [ ] A registered domain in Route 53 (or transferred into Route 53)
- [ ] AWS account ID handy (12-digit number)

---

## 4. Repository Structure

```
your-repo/
├── app.py                          ← Flask application
├── waveshare_can.py
├── can_tuner3.py
├── templates/
│   └── index.html
├── static/
│   ├── styles.css
│   └── app.js
├── tests/                          ← Add your pytest tests here
│   └── test_app.py
│
└── deployment/
    ├── docker/
    │   ├── Dockerfile
    │   ├── requirements.txt
    │   └── docker-compose.yml      ← Local dev
    ├── nginx/
    │   └── nginx.conf
    ├── jenkins/
    │   ├── Jenkinsfile
    │   └── jenkins-setup.sh
    └── terraform/
        ├── main.tf
        ├── variables.tf
        ├── modules/
        │   ├── vpc/main.tf
        │   ├── alb/main.tf
        │   ├── ecs/main.tf
        │   └── route53/main.tf
        └── environments/
            └── prod/
                └── terraform.tfvars.example
```

**Move files into correct positions:**
```bash
# From your repo root
mkdir -p templates static tests
cp deployment/docker/Dockerfile .     # OR build context = repo root
mv index.html templates/
mv styles.css app.js static/
cp deployment/docker/requirements.txt .
```

---

## 5. Step 1 — Bootstrap AWS Account

### 5a. Create S3 bucket for Terraform state
```bash
# Replace ACCOUNT_ID with your 12-digit AWS account ID
aws s3api create-bucket \
  --bucket can-tuner-terraform-state \
  --region ap-south-1 \
  --create-bucket-configuration LocationConstraint=ap-south-1

aws s3api put-bucket-versioning \
  --bucket can-tuner-terraform-state \
  --versioning-configuration Status=Enabled

aws s3api put-bucket-encryption \
  --bucket can-tuner-terraform-state \
  --server-side-encryption-configuration \
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
```

### 5b. Create DynamoDB table for state locking
```bash
aws dynamodb create-table \
  --table-name can-tuner-tf-lock \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region ap-south-1
```

### 5c. Create IAM user for Jenkins (least privilege)
```bash
aws iam create-user --user-name jenkins-deployer

# Attach policy (save as jenkins-policy.json first — see below)
aws iam put-user-policy \
  --user-name jenkins-deployer \
  --policy-name jenkins-deploy-policy \
  --policy-document file://jenkins-policy.json

# Create access key → SAVE THESE, you'll add them to Jenkins credentials
aws iam create-access-key --user-name jenkins-deployer
```

**jenkins-policy.json** (minimum permissions):
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ecr:GetAuthorizationToken",
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchGetImage",
        "ecr:PutImage",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ecs:DescribeTaskDefinition",
        "ecs:RegisterTaskDefinition",
        "ecs:UpdateService",
        "ecs:DescribeServices",
        "ecs:ListTasks",
        "ecs:DescribeTasks"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": ["iam:PassRole"],
      "Resource": "arn:aws:iam::*:role/can-tuner-ecs-*"
    }
  ]
}
```

### 5d. Request ACM Certificate
```bash
# This must be done in the SAME region as your ALB (ap-south-1)
aws acm request-certificate \
  --domain-name "yourdomain.com" \
  --subject-alternative-names "*.yourdomain.com" \
  --validation-method DNS \
  --region ap-south-1
```
> Go to **ACM Console → Certificates → your cert → Create DNS records in Route 53**  
> Wait until status shows **Issued** (5–10 minutes)

---

## 6. Step 2 — Launch Jenkins EC2

### Launch instance
1. Go to **EC2 Console → Launch Instance**
2. **Name:** `jenkins-server`
3. **AMI:** Ubuntu Server 22.04 LTS (64-bit x86)
4. **Instance type:** `t3.medium` (2 vCPU, 4 GB RAM — minimum for Jenkins + Docker)
5. **Key pair:** Create or select an existing key pair
6. **Security Group — Inbound rules:**

   | Port | Source | Purpose |
   |------|--------|---------|
   | 22 | Your IP only | SSH |
   | 8080 | Your IP only | Jenkins UI |
   | 443 | 0.0.0.0/0 | If you put Jenkins behind HTTPS |

7. **Storage:** 30 GB gp3
8. **IAM Instance Profile:** Attach a role with `AmazonEC2ContainerRegistryPowerUser` (optional — you can use static credentials instead)

### Run the setup script
```bash
# SSH into the instance
ssh -i your-key.pem ubuntu@<EC2_PUBLIC_IP>

# Upload and run the setup script
scp -i your-key.pem deployment/jenkins/jenkins-setup.sh ubuntu@<EC2_PUBLIC_IP>:~/
ssh -i your-key.pem ubuntu@<EC2_PUBLIC_IP> "sudo bash jenkins-setup.sh"
```

The script prints the **Jenkins initial admin password** at the end. Save it.

---

## 7. Step 3 — Configure Jenkins

### 7a. Unlock Jenkins
Open `http://<JENKINS_EC2_IP>:8080` and enter the initial admin password.

### 7b. Install Plugins
After unlocking, choose **Install suggested plugins**, then also install:

- **Blue Ocean** (better pipeline UI)
- **Amazon ECR** (`amazon-ecr`)
- **AWS Credentials** (`aws-credentials`)
- **AWS Steps** (`pipeline-aws`)
- **Slack Notification** (`slack`)
- **AnsiColor** (`ansicolor`)
- **Git** (usually pre-installed)

### 7c. Add Credentials
Go to **Manage Jenkins → Credentials → System → Global credentials → Add Credential**

| ID | Type | Value |
|----|------|-------|
| `aws-jenkins-deploy` | AWS Credentials | Access key ID + Secret from Step 5c |
| `ecr-registry-url` | Secret text | `ACCOUNT_ID.dkr.ecr.ap-south-1.amazonaws.com` |
| `app-health-url` | Secret text | `https://tuner.yourdomain.com/health` |
| `slack-token` | Secret text | Your Slack bot token |

### 7d. Configure Slack (optional)
**Manage Jenkins → System → Slack:**
- Workspace: your Slack workspace
- Credential: `slack-token`
- Default channel: `#deployments`

---

## 8. Step 4 — Provision Infrastructure with Terraform

```bash
# On your LOCAL machine (not Jenkins)
cd deployment/terraform

# Copy and fill in your values
cp environments/prod/terraform.tfvars.example terraform.tfvars
nano terraform.tfvars   # Fill in domain_name, certificate_arn, account ID

# Initialise (downloads providers, connects to S3 backend)
terraform init

# Preview what will be created (~30 resources)
terraform plan -out=tfplan

# Apply — takes ~8 minutes
terraform apply tfplan
```

**Terraform creates:**
- VPC with public + private subnets across 2 AZs
- Internet Gateway + NAT Gateways
- Application Load Balancer + Target Group + Listeners
- ECS Cluster (Fargate) + Task Definition + Service
- ECR Repository
- Route 53 A-record alias
- IAM roles for ECS
- CloudWatch Log Group
- Auto Scaling policy

**Save the outputs:**
```bash
terraform output
# app_url            = "https://tuner.yourdomain.com"
# ecr_repository_url = "ACCOUNT_ID.dkr.ecr.ap-south-1.amazonaws.com/can-tuner"
# ecs_cluster_name   = "can-tuner-prod"
# ecs_service_name   = "can-tuner-prod-svc"
```

---

## 9. Step 5 — Build & Push First Docker Image

Before Jenkins can deploy, ECR needs at least one image.

```bash
# Set variables
AWS_REGION=ap-south-1
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_URI="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/can-tuner"

# Login to ECR
aws ecr get-login-password --region $AWS_REGION \
  | docker login --username AWS --password-stdin $ECR_URI

# Build from repo root
docker build -f deployment/docker/Dockerfile -t can-tuner:latest .

# Tag and push
docker tag can-tuner:latest "${ECR_URI}:latest"
docker push "${ECR_URI}:latest"

echo "First image pushed: ${ECR_URI}:latest"
```

---

## 10. Step 6 — Create Jenkins Pipeline

### 10a. Add your repo to Jenkins
1. **New Item → Pipeline → Name:** `can-tuner-deploy`
2. **Build Triggers:** Check `GitHub hook trigger for GITScm polling`  
   (or set up a webhook in GitHub: `http://<JENKINS_IP>:8080/github-webhook/`)
3. **Pipeline Definition:** `Pipeline script from SCM`
4. **SCM:** Git
5. **Repository URL:** your GitHub/GitLab/CodeCommit URL
6. **Credentials:** Add your Git credentials
7. **Branch:** `*/main`
8. **Script Path:** `deployment/jenkins/Jenkinsfile`

### 10b. Update Jenkinsfile with your values
Edit `deployment/jenkins/Jenkinsfile` and update:
```groovy
ECR_REGISTRY  = credentials('ecr-registry-url')
ECS_CLUSTER   = 'can-tuner-prod'     // from terraform output
ECS_SERVICE   = 'can-tuner-prod-svc' // from terraform output
```

### 10c. Trigger first pipeline run
Click **Build Now** in Jenkins. Watch the Blue Ocean view.

**Pipeline stages visualised:**
```
[Checkout] → [Lint] → [Test] → [Docker Build] → [Push ECR] → [Deploy ECS] → [Verify] ✓
```

---

## 11. Step 7 — DNS & HTTPS with Route 53

If you registered your domain externally (GoDaddy, Namecheap, etc.):

### 11a. Create Hosted Zone
```bash
aws route53 create-hosted-zone \
  --name yourdomain.com \
  --caller-reference $(date +%s)
```

### 11b. Update nameservers at your registrar
```bash
# Get the 4 NS records AWS assigned
aws route53 list-hosted-zones-by-name --dns-name yourdomain.com \
  --query 'HostedZones[0].Id' --output text | xargs -I{} \
  aws route53 get-hosted-zone --id {} \
  --query 'DelegationSet.NameServers'
```
Go to your domain registrar and replace the nameservers with these 4 AWS nameservers.
**DNS propagation takes 10 minutes to 48 hours.**

### 11c. Verify DNS
```bash
# After propagation:
nslookup tuner.yourdomain.com
# Should resolve to the ALB IP(s)

curl -I https://tuner.yourdomain.com/health
# HTTP/2 200
```

---

## 12. Step 8 — Verify End-to-End

```bash
# 1. Check ECS service
aws ecs describe-services \
  --cluster can-tuner-prod \
  --services can-tuner-prod-svc \
  --region ap-south-1 \
  --query 'services[0].{Status:status,Running:runningCount,Desired:desiredCount}'

# 2. Check health endpoint
curl https://tuner.yourdomain.com/health

# 3. Check CloudWatch logs
aws logs tail /ecs/can-tuner/prod --follow --region ap-south-1

# 4. Open the app
open https://tuner.yourdomain.com
```

---

## 13. Day-2 Operations

### Deploy a new version
Just `git push origin main` — Jenkins picks it up automatically.

### Manual rollback
```bash
# List recent task definition revisions
aws ecs list-task-definitions \
  --family-prefix can-tuner-prod \
  --region ap-south-1 \
  --sort DESC

# Roll back to a specific revision
aws ecs update-service \
  --cluster can-tuner-prod \
  --service can-tuner-prod-svc \
  --task-definition can-tuner-prod:42 \   # ← the revision you want
  --region ap-south-1
```

### Scale manually
```bash
aws ecs update-service \
  --cluster can-tuner-prod \
  --service can-tuner-prod-svc \
  --desired-count 4 \
  --region ap-south-1
```

### View live logs
```bash
aws logs tail /ecs/can-tuner/prod --follow --region ap-south-1
```

### Destroy everything (careful!)
```bash
cd deployment/terraform
terraform destroy
```

---

## 14. Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| ECS tasks keep restarting | Health check `/health` failing | Add `/health` route to `app.py` (see below) |
| `ImagePullBackOff` | ECR auth expired or wrong image URI | Re-run Jenkins pipeline; check `app_image` in Terraform |
| 502 Bad Gateway from ALB | Flask not starting, wrong port | Check CloudWatch logs: `aws logs tail /ecs/can-tuner/prod` |
| Jenkins can't push to ECR | Missing IAM permissions | Verify `aws-jenkins-deploy` credentials and IAM policy |
| DNS not resolving | Nameservers not propagated | Wait 24–48 h; check with `dig tuner.yourdomain.com NS` |
| ACM certificate stuck "Pending" | DNS validation record not created | Go to ACM console → create validation record in Route 53 |

### Add /health endpoint to app.py
This is required for the ALB health check. Add this to `app.py`:

```python
@app.get("/health")
def health():
    return {"status": "ok"}, 200
```

---

## 15. Cost Estimate

Monthly costs in `ap-south-1` (Mumbai) with 2 tasks running 24/7:

| Service | Config | Est. $/month |
|---------|--------|--------------|
| ECS Fargate | 2 tasks × 0.5 vCPU × 1 GB | ~$18 |
| Application Load Balancer | 1 ALB + LCU | ~$20 |
| NAT Gateway | 2 AZs | ~$65 |
| ECR | 10 images × ~200 MB | ~$1 |
| Route 53 | 1 hosted zone + queries | ~$1 |
| CloudWatch Logs | 30-day retention | ~$2 |
| EC2 Jenkins | t3.medium, 24/7 | ~$28 |
| **Total** | | **~$135/month** |

**To reduce cost:**
- Use a single NAT Gateway (~$32 saved, minor HA tradeoff)
- Stop the Jenkins EC2 when not deploying
- Use FARGATE_SPOT for non-critical tasks (up to 70% cheaper)
- Reduce ECS desired count to 1 for dev/staging

---

*Generated for CAN Tuner Dashboard · AWS ap-south-1 · Terraform 1.6+ · Jenkins LTS*
