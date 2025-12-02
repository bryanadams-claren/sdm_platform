# Teardown all infrastructure for SDM Platform
param(
    [string]$ProjectName = "sdm-platform",
    [string]$Environment = "dev",
    [switch]$Force,
    [switch]$SkipConfirmation
)

# Import helper functions
. "$PSScriptRoot\aws_config_helpers.ps1"

Write-Host "========================================" -ForegroundColor Red
Write-Host "SDM Platform Infrastructure Teardown" -ForegroundColor Red
Write-Host "========================================" -ForegroundColor Red
Write-Host ""

# Load configuration
$configFile = Get-ConfigFilePath -ProjectName $ProjectName -Environment $Environment

if (-not (Test-Path $configFile)) {
    Write-Host "No configuration file found at: $configFile" -ForegroundColor Yellow
    Write-Host "Nothing to tear down." -ForegroundColor Green
    exit 0
}

Write-Host "This will DELETE the following infrastructure:" -ForegroundColor Yellow
Show-AwsConfig -ProjectName $ProjectName -Environment $Environment

if (-not $SkipConfirmation -and -not $Force) {
    Write-Host ""
    Write-Host "WARNING: This action CANNOT be undone!" -ForegroundColor Red
    Write-Host "Type 'DELETE' to confirm: " -ForegroundColor Yellow -NoNewline
    $confirmation = Read-Host

    if ($confirmation -ne "DELETE") {
        Write-Host "Teardown cancelled." -ForegroundColor Green
        exit 0
    }
}

# Load all config values
$Region = Get-AwsConfig -Key "REGION" -ProjectName $ProjectName -Environment $Environment
$VpcId = Get-AwsConfig -Key "VPC_ID" -ProjectName $ProjectName -Environment $Environment
$WebEnvName = Get-AwsConfig -Key "WEB_ENV_NAME" -ProjectName $ProjectName -Environment $Environment
$WorkerEnvName = Get-AwsConfig -Key "WORKER_ENV_NAME" -ProjectName $ProjectName -Environment $Environment
$RedisClusterId = Get-AwsConfig -Key "REDIS_CLUSTER_ID" -ProjectName $ProjectName -Environment $Environment
$RedisSubnetGroupName = Get-AwsConfig -Key "REDIS_SUBNET_GROUP_NAME" -ProjectName $ProjectName -Environment $Environment
$DbInstanceId = Get-AwsConfig -Key "DB_INSTANCE_ID" -ProjectName $ProjectName -Environment $Environment
$DbSubnetGroupName = Get-AwsConfig -Key "DB_SUBNET_GROUP_NAME" -ProjectName $ProjectName -Environment $Environment
$EbSgId = Get-AwsConfig -Key "EB_SG_ID" -ProjectName $ProjectName -Environment $Environment
$RdsSgId = Get-AwsConfig -Key "RDS_SG_ID" -ProjectName $ProjectName -Environment $Environment
$RedisSgId = Get-AwsConfig -Key "REDIS_SG_ID" -ProjectName $ProjectName -Environment $Environment
$IgwId = Get-AwsConfig -Key "IGW_ID" -ProjectName $ProjectName -Environment $Environment
$PublicSubnet1Id = Get-AwsConfig -Key "PUBLIC_SUBNET_1_ID" -ProjectName $ProjectName -Environment $Environment
$PublicSubnet2Id = Get-AwsConfig -Key "PUBLIC_SUBNET_2_ID" -ProjectName $ProjectName -Environment $Environment
$PrivateSubnet1Id = Get-AwsConfig -Key "PRIVATE_SUBNET_1_ID" -ProjectName $ProjectName -Environment $Environment
$PrivateSubnet2Id = Get-AwsConfig -Key "PRIVATE_SUBNET_2_ID" -ProjectName $ProjectName -Environment $Environment

Write-Host ""
Write-Host "Starting teardown process..." -ForegroundColor Cyan

# Step 1: Terminate Elastic Beanstalk Environments
Write-Host "`n=== Step 1: Terminating Elastic Beanstalk Environments ===" -ForegroundColor Yellow

if ($WebEnvName) {
    Write-Host "Terminating web environment: $WebEnvName"
    $webExists = aws elasticbeanstalk describe-environments `
        --environment-names $WebEnvName `
        --region $Region `
        --query "Environments[0].Status" `
        --output text 2>$null

    if ($webExists -and $webExists -ne "Terminated") {
        uv run eb terminate $WebEnvName --force
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Web environment terminated" -ForegroundColor Green
        }
    } else {
        Write-Host "Web environment already terminated or doesn't exist" -ForegroundColor Gray
    }
}

if ($WorkerEnvName) {
    Write-Host "Terminating worker environment: $WorkerEnvName"
    $workerExists = aws elasticbeanstalk describe-environments `
        --environment-names $WorkerEnvName `
        --region $Region `
        --query "Environments[0].Status" `
        --output text 2>$null

    if ($workerExists -and $workerExists -ne "Terminated") {
        uv run eb terminate $WorkerEnvName --force
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Worker environment terminated" -ForegroundColor Green
        }
    } else {
        Write-Host "Worker environment already terminated or doesn't exist" -ForegroundColor Gray
    }
}

# Step 2: Delete Redis Cluster
Write-Host "`n=== Step 2: Deleting Redis Cluster ===" -ForegroundColor Yellow

if ($RedisClusterId) {
    Write-Host "Deleting Redis cluster: $RedisClusterId"
    aws elasticache delete-cache-cluster `
        --cache-cluster-id $RedisClusterId `
        --region $Region 2>$null

    if ($LASTEXITCODE -eq 0) {
        Write-Host "Redis cluster deletion initiated (this takes a few minutes)" -ForegroundColor Green
        Write-Host "Waiting for Redis cluster to be deleted..."

        # Wait for cluster to be deleted
        $maxWait = 300 # 5 minutes
        $waited = 0
        while ($waited -lt $maxWait) {
            $clusterStatus = aws elasticache describe-cache-clusters `
                --cache-cluster-id $RedisClusterId `
                --region $Region `
                --query "CacheClusters[0].CacheClusterStatus" `
                --output text 2>$null

            if ($LASTEXITCODE -ne 0) {
                Write-Host "Redis cluster deleted" -ForegroundColor Green
                break
            }

            Write-Host "  Waiting... ($waited seconds)" -ForegroundColor Gray
            Start-Sleep -Seconds 10
            $waited += 10
        }
    } else {
        Write-Host "Redis cluster doesn't exist or already deleted" -ForegroundColor Gray
    }
}

# Delete Redis Subnet Group
if ($RedisSubnetGroupName) {
    Write-Host "Deleting Redis subnet group: $RedisSubnetGroupName"
    aws elasticache delete-cache-subnet-group `
        --cache-subnet-group-name $RedisSubnetGroupName `
        --region $Region 2>$null

    if ($LASTEXITCODE -eq 0) {
        Write-Host "Redis subnet group deleted" -ForegroundColor Green
    } else {
        Write-Host "Redis subnet group doesn't exist or already deleted" -ForegroundColor Gray
    }
}

# Step 3: Delete RDS Instance
Write-Host "`n=== Step 3: Deleting RDS Instance ===" -ForegroundColor Yellow

if ($DbInstanceId) {
    Write-Host "Deleting RDS instance: $DbInstanceId (skip final snapshot)"
    aws rds delete-db-instance `
        --db-instance-identifier $DbInstanceId `
        --skip-final-snapshot `
        --region $Region 2>$null

    if ($LASTEXITCODE -eq 0) {
        Write-Host "RDS instance deletion initiated (this takes 5-10 minutes)" -ForegroundColor Green
        Write-Host "Waiting for RDS instance to be deleted..."

        aws rds wait db-instance-deleted `
            --db-instance-identifier $DbInstanceId `
            --region $Region 2>$null

        Write-Host "RDS instance deleted" -ForegroundColor Green
    } else {
        Write-Host "RDS instance doesn't exist or already deleted" -ForegroundColor Gray
    }
}

# Delete DB Subnet Group
if ($DbSubnetGroupName) {
    Write-Host "Deleting DB subnet group: $DbSubnetGroupName"
    aws rds delete-db-subnet-group `
        --db-subnet-group-name $DbSubnetGroupName `
        --region $Region 2>$null

    if ($LASTEXITCODE -eq 0) {
        Write-Host "DB subnet group deleted" -ForegroundColor Green
    } else {
        Write-Host "DB subnet group doesn't exist or already deleted" -ForegroundColor Gray
    }
}

# Step 4: Delete Security Groups
Write-Host "`n=== Step 4: Deleting Security Groups ===" -ForegroundColor Yellow

# Wait a bit for resources to fully detach
Write-Host "Waiting 30 seconds for resources to detach from security groups..."
Start-Sleep -Seconds 30

foreach ($sgId in @($RedisSgId, $RdsSgId, $EbSgId)) {
    if ($sgId) {
        Write-Host "Deleting security group: $sgId"
        aws ec2 delete-security-group `
            --group-id $sgId `
            --region $Region 2>$null

        if ($LASTEXITCODE -eq 0) {
            Write-Host "Security group $sgId deleted" -ForegroundColor Green
        } else {
            Write-Host "Could not delete security group $sgId (may still be in use or already deleted)" -ForegroundColor Yellow
        }
    }
}

# Step 5: Delete Subnets
Write-Host "`n=== Step 5: Deleting Subnets ===" -ForegroundColor Yellow

foreach ($subnetId in @($PublicSubnet1Id, $PublicSubnet2Id, $PrivateSubnet1Id, $PrivateSubnet2Id)) {
    if ($subnetId) {
        Write-Host "Deleting subnet: $subnetId"
        aws ec2 delete-subnet `
            --subnet-id $subnetId `
            --region $Region 2>$null

        if ($LASTEXITCODE -eq 0) {
            Write-Host "Subnet $subnetId deleted" -ForegroundColor Green
        } else {
            Write-Host "Could not delete subnet $subnetId (may still be in use or already deleted)" -ForegroundColor Yellow
        }
    }
}

# Step 6: Detach and Delete Internet Gateway
Write-Host "`n=== Step 6: Deleting Internet Gateway ===" -ForegroundColor Yellow

if ($IgwId -and $VpcId) {
    Write-Host "Detaching Internet Gateway: $IgwId from VPC: $VpcId"
    aws ec2 detach-internet-gateway `
        --internet-gateway-id $IgwId `
        --vpc-id $VpcId `
        --region $Region 2>$null

    if ($LASTEXITCODE -eq 0) {
        Write-Host "Internet Gateway detached" -ForegroundColor Green
    }

    Write-Host "Deleting Internet Gateway: $IgwId"
    aws ec2 delete-internet-gateway `
        --internet-gateway-id $IgwId `
        --region $Region 2>$null

    if ($LASTEXITCODE -eq 0) {
        Write-Host "Internet Gateway deleted" -ForegroundColor Green
    } else {
        Write-Host "Could not delete Internet Gateway (may already be deleted)" -ForegroundColor Yellow
    }
}

# Step 7: Delete VPC
Write-Host "`n=== Step 7: Deleting VPC ===" -ForegroundColor Yellow

if ($VpcId) {
    Write-Host "Deleting VPC: $VpcId"
    aws ec2 delete-vpc `
        --vpc-id $VpcId `
        --region $Region 2>$null

    if ($LASTEXITCODE -eq 0) {
        Write-Host "VPC deleted" -ForegroundColor Green
    } else {
        Write-Host "Could not delete VPC (may have dependencies or already deleted)" -ForegroundColor Yellow
    }
}

# Step 8: Delete Config File
Write-Host "`n=== Step 8: Cleaning Up Configuration ===" -ForegroundColor Yellow

if (Test-Path $configFile) {
    Remove-Item $configFile -Force
    Write-Host "Configuration file deleted: $configFile" -ForegroundColor Green
} else {
    Write-Host "Configuration file already removed" -ForegroundColor Gray
}

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "Teardown Complete!" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Note: You may want to manually clean up:" -ForegroundColor Yellow
Write-Host "  - SSM Parameters in Parameter Store"
Write-Host "  - S3 buckets (if any were created)"
Write-Host "  - CloudWatch log groups"
Write-Host "  - Elastic Beanstalk application versions"
Write-Host ""
