# Create VPC for SDM Platform
param(
    [string]$Region = "us-east-2",
    [string]$ProjectName = "sdm-platform",
    [string]$Environment = "dev",
    [string]$CidrBlock = "10.0.0.0/16"
)

# Import helper functions
. "$PSScriptRoot\aws_config_helpers.ps1"

Write-Host "Creating VPC for $ProjectName ($Environment)..." -ForegroundColor Cyan

# Check if VPC already exists in config
$ExistingVpcId = Get-AwsConfig -Key "VPC_ID" -ProjectName $ProjectName -Environment $Environment

if ($ExistingVpcId) {
    # Verify it still exists in AWS
    $vpcExists = aws ec2 describe-vpcs `
        --vpc-ids $ExistingVpcId `
        --region $Region `
        --query "Vpcs[0].VpcId" `
        --output text 2>$null

    if ($vpcExists -eq $ExistingVpcId) {
        Write-Host "VPC already exists: $ExistingVpcId" -ForegroundColor Green
        $VpcId = $ExistingVpcId

        # Load other existing IDs
        $IgwId = Get-AwsConfig -Key "IGW_ID" -ProjectName $ProjectName -Environment $Environment
        $RouteTableId = Get-AwsConfig -Key "ROUTE_TABLE_ID" -ProjectName $ProjectName -Environment $Environment

        Write-Host "IGW: $IgwId" -ForegroundColor Gray
        Write-Host "Route Table: $RouteTableId" -ForegroundColor Gray

        Write-Host "`n=== VPC Already Configured! ===" -ForegroundColor Cyan
        Show-AwsConfig -ProjectName $ProjectName -Environment $Environment
        exit 0
    } else {
        Write-Host "VPC in config no longer exists in AWS, creating new one..." -ForegroundColor Yellow
    }
}

# Save basic config
Set-AwsConfig -Key "REGION" -Value $Region -ProjectName $ProjectName -Environment $Environment
Set-AwsConfig -Key "PROJECT_NAME" -Value $ProjectName -ProjectName $ProjectName -Environment $Environment
Set-AwsConfig -Key "ENVIRONMENT" -Value $Environment -ProjectName $ProjectName -Environment $Environment

# Create VPC
Write-Host "`n=== Step 1: Creating VPC ===" -ForegroundColor Yellow

$VpcId = aws ec2 create-vpc `
    --cidr-block $CidrBlock `
    --region $Region `
    --tag-specifications "ResourceType=vpc,Tags=[{Key=Name,Value=$ProjectName-$Environment-vpc},{Key=Project,Value=$ProjectName},{Key=Environment,Value=$Environment}]" `
    --query 'Vpc.VpcId' `
    --output text

if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to create VPC" -ForegroundColor Red
    exit 1
}

Write-Host "VPC created: $VpcId" -ForegroundColor Green
Set-AwsConfig -Key "VPC_ID" -Value $VpcId -ProjectName $ProjectName -Environment $Environment

# Enable DNS hostnames and DNS support
Write-Host "`n=== Step 2: Enabling DNS Support ===" -ForegroundColor Yellow

aws ec2 modify-vpc-attribute `
    --vpc-id $VpcId `
    --enable-dns-hostnames `
    --region $Region

aws ec2 modify-vpc-attribute `
    --vpc-id $VpcId `
    --enable-dns-support `
    --region $Region

Write-Host "DNS support enabled" -ForegroundColor Green

# Create Internet Gateway
Write-Host "`n=== Step 3: Creating Internet Gateway ===" -ForegroundColor Yellow

$IgwId = aws ec2 create-internet-gateway `
    --region $Region `
    --tag-specifications "ResourceType=internet-gateway,Tags=[{Key=Name,Value=$ProjectName-$Environment-igw},{Key=Project,Value=$ProjectName},{Key=Environment,Value=$Environment}]" `
    --query 'InternetGateway.InternetGatewayId' `
    --output text

if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to create Internet Gateway" -ForegroundColor Red
    exit 1
}

Write-Host "Internet Gateway created: $IgwId" -ForegroundColor Green
Set-AwsConfig -Key "IGW_ID" -Value $IgwId -ProjectName $ProjectName -Environment $Environment

# Attach Internet Gateway to VPC
aws ec2 attach-internet-gateway `
    --vpc-id $VpcId `
    --internet-gateway-id $IgwId `
    --region $Region

Write-Host "Internet Gateway attached to VPC" -ForegroundColor Green

# Create main route table and add route to IGW
Write-Host "`n=== Step 4: Configuring Route Table ===" -ForegroundColor Yellow

$RouteTableId = aws ec2 describe-route-tables `
    --filters "Name=vpc-id,Values=$VpcId" "Name=association.main,Values=true" `
    --region $Region `
    --query 'RouteTables[0].RouteTableId' `
    --output text

# Tag the main route table
aws ec2 create-tags `
    --resources $RouteTableId `
    --tags "Key=Name,Value=$ProjectName-$Environment-main-rt" "Key=Project,Value=$ProjectName" "Key=Environment,Value=$Environment" `
    --region $Region

Set-AwsConfig -Key "ROUTE_TABLE_ID" -Value $RouteTableId -ProjectName $ProjectName -Environment $Environment

# Add route to Internet Gateway
aws ec2 create-route `
    --route-table-id $RouteTableId `
    --destination-cidr-block 0.0.0.0/0 `
    --gateway-id $IgwId `
    --region $Region

Write-Host "Route to Internet Gateway added" -ForegroundColor Green

Write-Host "`n=== VPC Setup Complete! ===" -ForegroundColor Cyan
Show-AwsConfig -ProjectName $ProjectName -Environment $Environment

Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  Run: .\02_create_subnets.ps1"
