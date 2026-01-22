# Elastic Beanstalk Deployment Guide

## Overview

This project uses AWS Elastic Beanstalk for deploying both web and worker environments. The infrastructure is managed through PowerShell scripts and configuration files.

## Environment Information

### Current Environments

- **Web Environment**: `staging-LQM1lest`
  - Platform: Python 3.13 running on 64bit Amazon Linux 2023/4.9.1
  - Region: us-east-2
  - Domain: backpain.clarenhealth.com (and other journey subdomains)
  - Health check endpoint: `/health/`

- **Worker Environment**: (separate environment for Celery)
  - Platform: Python 3.13 running on 64bit Amazon Linux 2023/4.9.1
  - Region: us-east-2

### Infrastructure Resources

All infrastructure IDs are stored in `.envs/.local/.aws-sdm-platform-dev`:
- VPC: `vpc-029c9c656cb2fcac6`
- Public Subnets:
  - subnet-01e94d41bd02a6355
  - subnet-05327135b4a1cee81
- Security Groups:
  - EB: sg-0ca8f714bce8a6faf
  - RDS: sg-056983825f61a4f07
- RDS Database endpoint (stored in DATABASE_URL)
- Redis endpoint (stored in REDIS_URL)

## Deployment Commands

### Web Deployment

```powershell
# Deploy current code to web environment
uv run eb deploy --profile eb-cli

# Check environment status
uv run eb status --profile eb-cli

# View logs
uv run eb logs --profile eb-cli

# SSH into instance
uv run eb ssh --profile eb-cli
```

### Platform Upgrades

To upgrade the platform version (e.g., Python 3.13, Amazon Linux version):

```powershell
# Using AWS CLI (recommended for non-interactive upgrades)
aws elasticbeanstalk update-environment `
  --environment-name staging-LQM1lest `
  --option-settings Namespace=aws:elasticbeanstalk:container:python,OptionName=WSGIPath,Value=config/wsgi.py `
  --solution-stack-name "64bit Amazon Linux 2023 v4.9.1 running Python 3.13" `
  --profile eb-cli
```

## Configuration Files

### `.ebextensions/`

- **01_django.config**: Django environment variables (references AWS SSM parameters)
- **02_django_deploy.config**: Container commands for migrations, collectstatic, createcachetable
- **03_https.config**: HTTPS listener configuration with SSL certificate ARN
- **04_datadog.config**: Datadog monitoring setup

### Important Settings

#### ALLOWED_HOSTS (config/settings/production.py lines 23-38)

Dynamically adds internal IPs (10.x.x.x) for ELB health checks:

```python
ALLOWED_HOSTS = [
    ".clarenhealth.com",
    ".perspicacioushealth.com",
    ".elasticbeanstalk.com",
    ".backpaindecisionsupport.com",
]

# Allow all IPs in 10.0.0.0/8 range (VPC internal IPs) for ELB health checks
import socket
try:
    hostname = socket.gethostname()
    internal_ip = socket.gethostbyname(hostname)
    if internal_ip.startswith('10.'):
        ALLOWED_HOSTS.append(internal_ip)
except Exception:
    pass
```

#### Email Configuration (config/settings/production.py lines 154-183)

- Backend: `anymail.backends.amazon_ses.EmailBackend`
- Region: us-east-2
- From address: `Claren Health <no-reply@mail.clarenhealth.com>`
- IAM role: `aws-elasticbeanstalk-ec2-role` must have `ses:SendEmail` and `ses:SendRawEmail` permissions

## Infrastructure Setup Scripts

Located in `scripts/`:

- **02_create_subnets.ps1**: Creates VPC subnets
- **03_create_security_groups.ps1**: Creates security groups
- **06_create_web.ps1**: Creates web EB environment with proper VPC configuration
- **aws_config_helpers.ps1**: Helper functions for managing AWS config

These scripts store resource IDs in `.envs/.local/.aws-sdm-platform-dev` for reuse.

## Common Operations

### Viewing Logs

On the EC2 instance (via SSH):

```bash
# Main application log
tail -f /var/log/web.stdout.log

# EB deployment logs
tail -f /var/log/eb-engine.log
```

### Checking Environment Health

1. **AWS Console**: Check environment health status (should be Green)
2. **Target Groups**: Verify all targets are healthy (no HTTP 4xx errors)
3. **ELB Health Checks**: Ensure `/health/` endpoint returns 200

## Troubleshooting

### Environment Stuck in "Updating" or "Aborting"

If an environment becomes unresponsive:

1. Check if EC2 instances are healthy via AWS Console
2. If instances are unhealthy and blocking abort:
   ```powershell
   # Manually terminate unhealthy instances
   aws ec2 terminate-instances --instance-ids i-XXXXXXXXX --profile eb-cli
   ```
3. Wait for abort to complete, then recreate environment using `06_create_web.ps1`

### DisallowedHost Errors

- Internal IPs: Add to ALLOWED_HOSTS or ensure dynamic IP detection code is working
- Bot traffic: Ignore errors from random DNS names (e.g., EC2 public DNS)

## SSL Certificates

SSL certificates are managed via AWS Certificate Manager (ACM):

- Current wildcard cert: `*.clarenhealth.com` (ARN in `03_https.config`)
- Also covers: `clarenhealth.com` (apex domain)
- Certificate ARN: `arn:aws:acm:us-east-2:629490206438:certificate/3ec8fc28-ca62-498a-a901-d1f276834849`

To update certificate, modify `.ebextensions/03_https.config` or update via EB Console.

## Key Files to Review

- `.ebextensions/`: All EB configuration
- `.elasticbeanstalk/config.yml`: EB CLI configuration
- `config/settings/production.py`: Django production settings
- `.envs/.local/.aws-sdm-platform-dev`: Infrastructure resource IDs
- `scripts/06_create_web.ps1`: Environment creation script
