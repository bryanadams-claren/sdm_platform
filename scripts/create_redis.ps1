# Setup infrastructure for SDM Platform
param(
    [string]$VpcId = "vpc-0ea9b7f4341e4121e",
    [string]$Region = "us-east-2",
    [string]$ProjectName = "sdm-platform"
)

Write-Host "Setting up infrastructure for $ProjectName..." -ForegroundColor Cyan

# 1. Create ElastiCache subnet group (if it doesn't exist)
Write-Host "`n=== Step 1: ElastiCache Subnet Group ===" -ForegroundColor Yellow

$SubnetGroupName = "$ProjectName-redis-subnet-group"
$SubnetIds = "subnet-0d8fdf6b575253e49,subnet-036659884bdb99a58"

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

# 2. Create Redis security group (if it doesn't exist)
Write-Host "`n=== Step 2: Redis Security Group ===" -ForegroundColor Yellow

$RedisSgName = "$ProjectName-redis-sg"
$existingSg = aws ec2 describe-security-groups `
    --filters "Name=group-name,Values=$RedisSgName" "Name=vpc-id,Values=$VpcId" `
    --region $Region `
    --query "SecurityGroups[0].GroupId" `
    --output text 2>$null

if ($existingSg -and $existingSg -ne "None") {
    Write-Host "Security group '$RedisSgName' already exists: $existingSg" -ForegroundColor Green
    $RedisSgId = $existingSg
} else {
    Write-Host "Creating Redis security group..."
    $RedisSgId = aws ec2 create-security-group `
        --group-name $RedisSgName `
        --description "Security group for $ProjectName Redis" `
        --vpc-id $VpcId `
        --region $Region `
        --query 'GroupId' `
        --output text

    if ($LASTEXITCODE -eq 0) {
        Write-Host "Security group created: $RedisSgId" -ForegroundColor Green

        # Allow inbound Redis (port 6379) from EB instance security group
        $EbSgId = "sg-01980717819d4a489"
        Write-Host "Adding ingress rule for Redis port 6379 from EB security group..."
        aws ec2 authorize-security-group-ingress `
            --group-id $RedisSgId `
            --protocol tcp `
            --port 6379 `
            --source-group $EbSgId `
            --region $Region

        Write-Host "Ingress rule added" -ForegroundColor Green
    } else {
        Write-Host "Failed to create security group" -ForegroundColor Red
        exit 1
    }
}

# 3. Create ElastiCache Redis cluster (if it doesn't exist)
Write-Host "`n=== Step 3: ElastiCache Redis Cluster ===" -ForegroundColor Yellow

$ClusterName = "$ProjectName-redis"
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
        --region $Region

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

# 4. Get Redis endpoint and update SSM parameter
Write-Host "`n=== Step 4: Update SSM Parameter ===" -ForegroundColor Yellow

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

Write-Host "Redis URL: $RedisUrl"

# Update SSM parameter
aws ssm put-parameter `
    --name "/sdm_platform/REDIS_URL" `
    --value $RedisUrl `
    --type "SecureString" `
    --overwrite `
    --region $Region

if ($LASTEXITCODE -eq 0) {
    Write-Host "SSM parameter updated successfully" -ForegroundColor Green
} else {
    Write-Host "Failed to update SSM parameter" -ForegroundColor Red
}

Write-Host "`n=== Infrastructure Setup Complete! ===" -ForegroundColor Cyan
Write-Host "Redis Security Group ID: $RedisSgId"
Write-Host "Redis Endpoint: $RedisEndpoint"
Write-Host "Redis URL: $RedisUrl"
