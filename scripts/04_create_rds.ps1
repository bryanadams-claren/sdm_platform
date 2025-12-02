# Create RDS PostgreSQL instance for SDM Platform
param(
    [string]$VpcId,
    [string]$RdsSgId,
    [string]$PrivateSubnet1Id,
    [string]$PrivateSubnet2Id,
    [string]$Region,
    [string]$ProjectName = "sdm-platform",
    [string]$Environment = "dev",
    [string]$DbName = "sdm_platform",
    [string]$MasterUsername = "sdmdbuser",
    [string]$InstanceClass = "db.t3.micro",
    [int]$AllocatedStorage = 20
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
if (-not $RdsSgId) {
    $RdsSgId = Get-AwsConfig -Key "RDS_SG_ID" -ProjectName $ProjectName -Environment $Environment
}
if (-not $PrivateSubnet1Id) {
    $PrivateSubnet1Id = Get-AwsConfig -Key "PRIVATE_SUBNET_1_ID" -ProjectName $ProjectName -Environment $Environment
}
if (-not $PrivateSubnet2Id) {
    $PrivateSubnet2Id = Get-AwsConfig -Key "PRIVATE_SUBNET_2_ID" -ProjectName $ProjectName -Environment $Environment
}

if (-not $VpcId -or -not $RdsSgId -or -not $PrivateSubnet1Id -or -not $PrivateSubnet2Id) {
    Write-Host "Error: Missing required configuration. Run previous setup scripts first." -ForegroundColor Red
    Write-Host "  VPC_ID: $VpcId" -ForegroundColor Yellow
    Write-Host "  RDS_SG_ID: $RdsSgId" -ForegroundColor Yellow
    Write-Host "  PRIVATE_SUBNET_1_ID: $PrivateSubnet1Id" -ForegroundColor Yellow
    Write-Host "  PRIVATE_SUBNET_2_ID: $PrivateSubnet2Id" -ForegroundColor Yellow
    exit 1
}

Write-Host "Creating RDS PostgreSQL instance for $ProjectName..." -ForegroundColor Cyan

# Generate a random password
$MasterPassword = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 32 | ForEach-Object {[char]$_})
Write-Host "Generated master password (will be saved to config)" -ForegroundColor Yellow

# Create DB Subnet Group
Write-Host "`n=== Step 1: Creating DB Subnet Group ===" -ForegroundColor Yellow

$DbSubnetGroupName = "$ProjectName-$Environment-db-subnet-group"

$existingSubnetGroup = aws rds describe-db-subnet-groups `
    --db-subnet-group-name $DbSubnetGroupName `
    --region $Region 2>$null

if ($LASTEXITCODE -eq 0) {
    Write-Host "DB Subnet Group '$DbSubnetGroupName' already exists" -ForegroundColor Green
} else {
    Write-Host "Creating DB Subnet Group..."
    aws rds create-db-subnet-group `
        --db-subnet-group-name $DbSubnetGroupName `
        --db-subnet-group-description "Subnet group for $ProjectName RDS" `
        --subnet-ids $PrivateSubnet1Id $PrivateSubnet2Id `
        --tags "Key=Name,Value=$DbSubnetGroupName" "Key=Project,Value=$ProjectName" "Key=Environment,Value=$Environment" `
        --region $Region

    if ($LASTEXITCODE -eq 0) {
        Write-Host "DB Subnet Group created successfully" -ForegroundColor Green
    } else {
        Write-Host "Failed to create DB Subnet Group" -ForegroundColor Red
        exit 1
    }
}

Set-AwsConfig -Key "DB_SUBNET_GROUP_NAME" -Value $DbSubnetGroupName -ProjectName $ProjectName -Environment $Environment

# Create RDS instance
Write-Host "`n=== Step 2: Creating RDS PostgreSQL Instance ===" -ForegroundColor Yellow
Write-Host "This will take 5-10 minutes..." -ForegroundColor Yellow

$DbInstanceId = "$ProjectName-$Environment-db"

$existingDb = aws rds describe-db-instances `
    --db-instance-identifier $DbInstanceId `
    --region $Region 2>$null

if ($LASTEXITCODE -eq 0) {
    Write-Host "RDS instance '$DbInstanceId' already exists" -ForegroundColor Green
} else {
    Write-Host "Creating RDS instance..."
    aws rds create-db-instance `
        --db-instance-identifier $DbInstanceId `
        --db-instance-class $InstanceClass `
        --engine postgres `
        --engine-version 17.6 `
        --master-username $MasterUsername `
        --master-user-password $MasterPassword `
        --allocated-storage $AllocatedStorage `
        --db-name $DbName `
        --vpc-security-group-ids $RdsSgId `
        --db-subnet-group-name $DbSubnetGroupName `
        --backup-retention-period 7 `
        --preferred-backup-window "03:00-04:00" `
        --preferred-maintenance-window "mon:04:00-mon:05:00" `
        --no-publicly-accessible `
        --storage-encrypted `
        --tags "Key=Name,Value=$DbInstanceId" "Key=Project,Value=$ProjectName" "Key=Environment,Value=$Environment" `
        --region $Region

    if ($LASTEXITCODE -ne 0) {
        Write-Host "Failed to create RDS instance" -ForegroundColor Red
        exit 1
    }

    Write-Host "RDS instance creation initiated" -ForegroundColor Green
    Write-Host "Waiting for instance to be available (this takes ~5-10 minutes)..."

    aws rds wait db-instance-available `
        --db-instance-identifier $DbInstanceId `
        --region $Region

    Write-Host "RDS instance is now available!" -ForegroundColor Green
}

Set-AwsConfig -Key "DB_INSTANCE_ID" -Value $DbInstanceId -ProjectName $ProjectName -Environment $Environment
Set-AwsConfig -Key "DB_NAME" -Value $DbName -ProjectName $ProjectName -Environment $Environment
Set-AwsConfig -Key "DB_MASTER_USERNAME" -Value $MasterUsername -ProjectName $ProjectName -Environment $Environment
Set-AwsConfig -Key "DB_MASTER_PASSWORD" -Value $MasterPassword -ProjectName $ProjectName -Environment $Environment

# Get RDS endpoint
Write-Host "`n=== Step 3: Getting RDS Endpoint ===" -ForegroundColor Yellow

$DbEndpoint = aws rds describe-db-instances `
    --db-instance-identifier $DbInstanceId `
    --region $Region `
    --query "DBInstances[0].Endpoint.Address" `
    --output text

$DbPort = aws rds describe-db-instances `
    --db-instance-identifier $DbInstanceId `
    --region $Region `
    --query "DBInstances[0].Endpoint.Port" `
    --output text

$DatabaseUrl = "postgres://${MasterUsername}:${MasterPassword}@${DbEndpoint}:${DbPort}/${DbName}"

Write-Host "Database endpoint: $DbEndpoint" -ForegroundColor Green
Write-Host "Database URL: postgres://${MasterUsername}:****@${DbEndpoint}:${DbPort}/${DbName}"

Set-AwsConfig -Key "DB_ENDPOINT" -Value $DbEndpoint -ProjectName $ProjectName -Environment $Environment
Set-AwsConfig -Key "DB_PORT" -Value $DbPort -ProjectName $ProjectName -Environment $Environment
Set-AwsConfig -Key "DATABASE_URL" -Value $DatabaseUrl -ProjectName $ProjectName -Environment $Environment

# Store credentials in SSM Parameter Store
Write-Host "`n=== Step 4: Storing Credentials in SSM ===" -ForegroundColor Yellow

aws ssm put-parameter `
    --name "/sdm_platform/DATABASE_URL" `
    --value $DatabaseUrl `
    --type "String" `
    --overwrite `
    --region $Region

if ($LASTEXITCODE -eq 0) {
    Write-Host "DATABASE_URL stored in SSM Parameter Store" -ForegroundColor Green
} else {
    Write-Host "Failed to store DATABASE_URL in SSM" -ForegroundColor Red
}

Write-Host "`n=== RDS Setup Complete! ===" -ForegroundColor Cyan
Show-AwsConfig -ProjectName $ProjectName -Environment $Environment

Write-Host "`nIMPORTANT: Database credentials saved to local config file" -ForegroundColor Yellow
Write-Host "The DATABASE_URL has been stored in SSM Parameter Store at: /$ProjectName/DATABASE_URL" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  Run: .\05_create_redis.ps1 (use values from config above)"
Write-Host "  Run: .\06_create_web.ps1 (use values from config above)"
Write-Host "  Run: .\07_create_worker.ps1 (use values from config above)"
