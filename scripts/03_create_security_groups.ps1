# Create security groups for SDM Platform
param(
    [string]$VpcId,
    [string]$Region,
    [string]$ProjectName = "sdm-platform",
    [string]$Environment = "dev"
)

# Import helper functions
. "$PSScriptRoot\aws_config_helpers.ps1"

# Load config if not provided
if (-not $VpcId) {
    $VpcId = Get-AwsConfig -Key "VPC_ID" -ProjectName $ProjectName -Environment $Environment
}
if (-not $Region) {
    $Region = Get-AwsConfig -Key "REGION" -ProjectName $ProjectName -Environment $Environment
}

if (-not $VpcId) {
    Write-Host "Error: VPC_ID not found. Run 01_create_vpc.ps1 first." -ForegroundColor Red
    exit 1
}

# Check if security groups already exist
$ExistingEbSg = Get-AwsConfig -Key "EB_SG_ID" -ProjectName $ProjectName -Environment $Environment
$ExistingRdsSg = Get-AwsConfig -Key "RDS_SG_ID" -ProjectName $ProjectName -Environment $Environment
$ExistingRedisSg = Get-AwsConfig -Key "REDIS_SG_ID" -ProjectName $ProjectName -Environment $Environment

if ($ExistingEbSg -and $ExistingRdsSg -and $ExistingRedisSg) {
    Write-Host "Security groups already configured:" -ForegroundColor Green
    Write-Host "  EB Security Group: $ExistingEbSg" -ForegroundColor Gray
    Write-Host "  RDS Security Group: $ExistingRdsSg" -ForegroundColor Gray
    Write-Host "  Redis Security Group: $ExistingRedisSg" -ForegroundColor Gray
    Write-Host "`nSkipping security group creation (already exists)" -ForegroundColor Yellow
    Show-AwsConfig -ProjectName $ProjectName -Environment $Environment
    exit 0
}

Write-Host "Creating security groups for $ProjectName in VPC $VpcId..." -ForegroundColor Cyan

# Create Elastic Beanstalk EC2 Security Group
Write-Host "`n=== Creating EB EC2 Security Group ===" -ForegroundColor Yellow

$EbSgId = aws ec2 create-security-group `
    --group-name "$ProjectName-$Environment-eb-sg" `
    --description "Security group for $ProjectName Elastic Beanstalk EC2 instances" `
    --vpc-id $VpcId `
    --region $Region `
    --tag-specifications "ResourceType=security-group,Tags=[{Key=Name,Value=$ProjectName-$Environment-eb-sg},{Key=Project,Value=$ProjectName},{Key=Environment,Value=$Environment}]" `
    --query 'GroupId' `
    --output text

if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to create EB EC2 Security Group" -ForegroundColor Red
    exit 1
}

Write-Host "EB EC2 Security Group created: $EbSgId" -ForegroundColor Green
Set-AwsConfig -Key "EB_SG_ID" -Value $EbSgId -ProjectName $ProjectName -Environment $Environment

# Add ingress rules for EB SG
Write-Host "Adding ingress rules for EB EC2..."

# Allow HTTP from anywhere (for ALB)
aws ec2 authorize-security-group-ingress `
    --group-id $EbSgId `
    --protocol tcp `
    --port 80 `
    --cidr 0.0.0.0/0 `
    --region $Region

# Allow HTTPS from anywhere (for ALB)
aws ec2 authorize-security-group-ingress `
    --group-id $EbSgId `
    --protocol tcp `
    --port 443 `
    --cidr 0.0.0.0/0 `
    --region $Region

# Allow SSH from anywhere (for debugging - consider restricting this)
aws ec2 authorize-security-group-ingress `
    --group-id $EbSgId `
    --protocol tcp `
    --port 22 `
    --cidr 0.0.0.0/0 `
    --region $Region

Write-Host "EB EC2 ingress rules added" -ForegroundColor Green

# Create RDS Security Group
Write-Host "`n=== Creating RDS Security Group ===" -ForegroundColor Yellow

$RdsSgId = aws ec2 create-security-group `
    --group-name "$ProjectName-$Environment-rds-sg" `
    --description "Security group for $ProjectName RDS PostgreSQL" `
    --vpc-id $VpcId `
    --region $Region `
    --tag-specifications "ResourceType=security-group,Tags=[{Key=Name,Value=$ProjectName-$Environment-rds-sg},{Key=Project,Value=$ProjectName},{Key=Environment,Value=$Environment}]" `
    --query 'GroupId' `
    --output text

if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to create RDS Security Group" -ForegroundColor Red
    exit 1
}

Write-Host "RDS Security Group created: $RdsSgId" -ForegroundColor Green
Set-AwsConfig -Key "RDS_SG_ID" -Value $RdsSgId -ProjectName $ProjectName -Environment $Environment

# Allow PostgreSQL from EB instances
Write-Host "Adding ingress rule for RDS (PostgreSQL port 5432)..."
aws ec2 authorize-security-group-ingress `
    --group-id $RdsSgId `
    --protocol tcp `
    --port 5432 `
    --source-group $EbSgId `
    --region $Region

Write-Host "RDS ingress rule added" -ForegroundColor Green

# Create Redis Security Group
Write-Host "`n=== Creating Redis Security Group ===" -ForegroundColor Yellow

$RedisSgId = aws ec2 create-security-group `
    --group-name "$ProjectName-$Environment-redis-sg" `
    --description "Security group for $ProjectName Redis" `
    --vpc-id $VpcId `
    --region $Region `
    --tag-specifications "ResourceType=security-group,Tags=[{Key=Name,Value=$ProjectName-$Environment-redis-sg},{Key=Project,Value=$ProjectName},{Key=Environment,Value=$Environment}]" `
    --query 'GroupId' `
    --output text

if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to create Redis Security Group" -ForegroundColor Red
    exit 1
}

Write-Host "Redis Security Group created: $RedisSgId" -ForegroundColor Green
Set-AwsConfig -Key "REDIS_SG_ID" -Value $RedisSgId -ProjectName $ProjectName -Environment $Environment

# Allow Redis from EB instances
Write-Host "Adding ingress rule for Redis (port 6379)..."
aws ec2 authorize-security-group-ingress `
    --group-id $RedisSgId `
    --protocol tcp `
    --port 6379 `
    --source-group $EbSgId `
    --region $Region

Write-Host "Redis ingress rule added" -ForegroundColor Green

Write-Host "`n=== Security Group Setup Complete! ===" -ForegroundColor Cyan
Show-AwsConfig -ProjectName $ProjectName -Environment $Environment

Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  Run: .\04_create_rds.ps1"
