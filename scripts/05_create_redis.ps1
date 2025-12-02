# Setup Redis infrastructure for SDM Platform
param(
    [string]$VpcId,
    [string]$RedisSgId,
    [string]$PublicSubnet1Id,
    [string]$PublicSubnet2Id,
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
if (-not $RedisSgId) {
    $RedisSgId = Get-AwsConfig -Key "REDIS_SG_ID" -ProjectName $ProjectName -Environment $Environment
}
if (-not $PublicSubnet1Id) {
    $PublicSubnet1Id = Get-AwsConfig -Key "PUBLIC_SUBNET_1_ID" -ProjectName $ProjectName -Environment $Environment
}
if (-not $PublicSubnet2Id) {
    $PublicSubnet2Id = Get-AwsConfig -Key "PUBLIC_SUBNET_2_ID" -ProjectName $ProjectName -Environment $Environment
}

if (-not $VpcId -or -not $RedisSgId -or -not $PublicSubnet1Id -or -not $PublicSubnet2Id) {
    Write-Host "Error: Missing required configuration. Run previous setup scripts first." -ForegroundColor Red
    Write-Host "  VPC_ID: $VpcId" -ForegroundColor Yellow
    Write-Host "  REDIS_SG_ID: $RedisSgId" -ForegroundColor Yellow
    Write-Host "  PUBLIC_SUBNET_1_ID: $PublicSubnet1Id" -ForegroundColor Yellow
    Write-Host "  PUBLIC_SUBNET_2_ID: $PublicSubnet2Id" -ForegroundColor Yellow
    exit 1
}

Write-Host "Setting up Redis for $ProjectName ($Environment)..." -ForegroundColor Cyan

# 1. Create ElastiCache subnet group (if it doesn't exist)
Write-Host "`n=== Step 1: ElastiCache Subnet Group ===" -ForegroundColor Yellow

$SubnetGroupName = "$ProjectName-$Environment-redis-subnet-group"
$SubnetIds = "$PublicSubnet1Id,$PublicSubnet2Id"

$existingSubnetGroup = aws elasticache describe-cache-subnet-groups `
    --cache-subnet-group-name $SubnetGroupName `
    --region $Region 2>$null

if ($LASTEXITCODE -eq 0) {
    Write-Host "Subnet group '$SubnetGroupName' already exists" -ForegroundColor Green
} else {
    Write-Host "Creating subnet group '$SubnetGroupName'..."
    aws elasticache create-cache-subnet-group `
        --cache-subnet-group-name $SubnetGroupName `
        --cache-subnet-group-description "Subnet group for $ProjectName Redis" `
        --subnet-ids $SubnetIds.Split(',') `
        --region $Region

    if ($LASTEXITCODE -eq 0) {
        Write-Host "Subnet group created successfully" -ForegroundColor Green
    } else {
        Write-Host "Failed to create subnet group" -ForegroundColor Red
        exit 1
    }
}

Set-AwsConfig -Key "REDIS_SUBNET_GROUP_NAME" -Value $SubnetGroupName -ProjectName $ProjectName -Environment $Environment

# 2. Create ElastiCache Redis cluster (if it doesn't exist)
Write-Host "`n=== Step 2: ElastiCache Redis Cluster ===" -ForegroundColor Yellow

$ClusterName = "$ProjectName-$Environment-redis"
$existingCluster = aws elasticache describe-cache-clusters `
    --cache-cluster-id $ClusterName `
    --region $Region 2>$null

if ($LASTEXITCODE -eq 0) {
    Write-Host "Redis cluster '$ClusterName' already exists" -ForegroundColor Green
} else {
    Write-Host "Creating Redis cluster (this takes ~5-10 minutes)..."
    aws elasticache create-cache-cluster `
        --cache-cluster-id $ClusterName `
        --cache-node-type cache.t3.micro `
        --engine redis `
        --engine-version 7.0 `
        --num-cache-nodes 1 `
        --cache-subnet-group-name $SubnetGroupName `
        --security-group-ids $RedisSgId `
        --region $Region `
        --tags "Key=Name,Value=$ClusterName" "Key=Project,Value=$ProjectName" "Key=Environment,Value=$Environment"

    if ($LASTEXITCODE -eq 0) {
        Write-Host "Redis cluster creation initiated" -ForegroundColor Green
        Write-Host "Waiting for cluster to be available..."

        aws elasticache wait cache-cluster-available `
            --cache-cluster-id $ClusterName `
            --region $Region

        Write-Host "Redis cluster is now available!" -ForegroundColor Green
    } else {
        Write-Host "Failed to create Redis cluster" -ForegroundColor Red
        exit 1
    }
}

Set-AwsConfig -Key "REDIS_CLUSTER_ID" -Value $ClusterName -ProjectName $ProjectName -Environment $Environment

# 3. Get Redis endpoint and update SSM parameter
Write-Host "`n=== Step 3: Get Redis Endpoint and Update SSM ===" -ForegroundColor Yellow

$RedisEndpoint = aws elasticache describe-cache-clusters `
    --cache-cluster-id $ClusterName `
    --show-cache-node-info `
    --region $Region `
    --query "CacheClusters[0].CacheNodes[0].Endpoint.Address" `
    --output text

$RedisPort = aws elasticache describe-cache-clusters `
    --cache-cluster-id $ClusterName `
    --show-cache-node-info `
    --region $Region `
    --query "CacheClusters[0].CacheNodes[0].Endpoint.Port" `
    --output text

$RedisUrl = "redis://${RedisEndpoint}:${RedisPort}/0"

Write-Host "Redis URL: $RedisUrl" -ForegroundColor Green

Set-AwsConfig -Key "REDIS_ENDPOINT" -Value $RedisEndpoint -ProjectName $ProjectName -Environment $Environment
Set-AwsConfig -Key "REDIS_PORT" -Value $RedisPort -ProjectName $ProjectName -Environment $Environment
Set-AwsConfig -Key "REDIS_URL" -Value $RedisUrl -ProjectName $ProjectName -Environment $Environment

# Update SSM parameter
aws ssm put-parameter `
    --name "/sdm_platform/REDIS_URL" `
    --value $RedisUrl `
    --type "String" `
    --overwrite `
    --region $Region

if ($LASTEXITCODE -eq 0) {
    Write-Host "SSM parameter updated successfully" -ForegroundColor Green
} else {
    Write-Host "Failed to update SSM parameter" -ForegroundColor Red
}

Write-Host "`n=== Redis Setup Complete! ===" -ForegroundColor Cyan
Show-AwsConfig -ProjectName $ProjectName -Environment $Environment

Write-Host "`nNext steps:" -ForegroundColor Yellow
Write-Host "  1. Terminate existing EB environments if needed"
Write-Host "  2. Run: .\06_create_web.ps1"
Write-Host "  3. Run: .\07_create_worker.ps1"
