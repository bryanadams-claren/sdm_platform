# Create subnets for SDM Platform
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

# Check if subnets already exist
$ExistingSubnet1 = Get-AwsConfig -Key "PUBLIC_SUBNET_1_ID" -ProjectName $ProjectName -Environment $Environment
$ExistingSubnet2 = Get-AwsConfig -Key "PUBLIC_SUBNET_2_ID" -ProjectName $ProjectName -Environment $Environment
$ExistingPrivate1 = Get-AwsConfig -Key "PRIVATE_SUBNET_1_ID" -ProjectName $ProjectName -Environment $Environment
$ExistingPrivate2 = Get-AwsConfig -Key "PRIVATE_SUBNET_2_ID" -ProjectName $ProjectName -Environment $Environment

if ($ExistingSubnet1 -and $ExistingSubnet2 -and $ExistingPrivate1 -and $ExistingPrivate2) {
    Write-Host "Subnets already configured:" -ForegroundColor Green
    Write-Host "  Public Subnet 1: $ExistingSubnet1" -ForegroundColor Gray
    Write-Host "  Public Subnet 2: $ExistingSubnet2" -ForegroundColor Gray
    Write-Host "  Private Subnet 1: $ExistingPrivate1" -ForegroundColor Gray
    Write-Host "  Private Subnet 2: $ExistingPrivate2" -ForegroundColor Gray
    Write-Host "`nSkipping subnet creation (already exists)" -ForegroundColor Yellow
    Show-AwsConfig -ProjectName $ProjectName -Environment $Environment
    exit 0
}

Write-Host "Creating subnets for $ProjectName in VPC $VpcId..." -ForegroundColor Cyan

# Define availability zones and CIDR blocks
$Az1 = "${Region}a"
$Az2 = "${Region}b"
$PublicSubnet1Cidr = "10.0.1.0/24"
$PublicSubnet2Cidr = "10.0.2.0/24"
$PrivateSubnet1Cidr = "10.0.10.0/24"
$PrivateSubnet2Cidr = "10.0.11.0/24"

# Create Public Subnet 1
Write-Host "`n=== Creating Public Subnet 1 ($Az1) ===" -ForegroundColor Yellow

$PublicSubnet1Id = aws ec2 create-subnet `
    --vpc-id $VpcId `
    --cidr-block $PublicSubnet1Cidr `
    --availability-zone $Az1 `
    --region $Region `
    --tag-specifications "ResourceType=subnet,Tags=[{Key=Name,Value=$ProjectName-$Environment-public-subnet-1},{Key=Project,Value=$ProjectName},{Key=Environment,Value=$Environment},{Key=Type,Value=Public}]" `
    --query 'Subnet.SubnetId' `
    --output text

Write-Host "Public Subnet 1 created: $PublicSubnet1Id" -ForegroundColor Green
Set-AwsConfig -Key "PUBLIC_SUBNET_1_ID" -Value $PublicSubnet1Id -ProjectName $ProjectName -Environment $Environment
Set-AwsConfig -Key "PUBLIC_SUBNET_1_AZ" -Value $Az1 -ProjectName $ProjectName -Environment $Environment

# Enable auto-assign public IP
aws ec2 modify-subnet-attribute `
    --subnet-id $PublicSubnet1Id `
    --map-public-ip-on-launch `
    --region $Region

# Create Public Subnet 2
Write-Host "`n=== Creating Public Subnet 2 ($Az2) ===" -ForegroundColor Yellow

$PublicSubnet2Id = aws ec2 create-subnet `
    --vpc-id $VpcId `
    --cidr-block $PublicSubnet2Cidr `
    --availability-zone $Az2 `
    --region $Region `
    --tag-specifications "ResourceType=subnet,Tags=[{Key=Name,Value=$ProjectName-$Environment-public-subnet-2},{Key=Project,Value=$ProjectName},{Key=Environment,Value=$Environment},{Key=Type,Value=Public}]" `
    --query 'Subnet.SubnetId' `
    --output text

Write-Host "Public Subnet 2 created: $PublicSubnet2Id" -ForegroundColor Green
Set-AwsConfig -Key "PUBLIC_SUBNET_2_ID" -Value $PublicSubnet2Id -ProjectName $ProjectName -Environment $Environment
Set-AwsConfig -Key "PUBLIC_SUBNET_2_AZ" -Value $Az2 -ProjectName $ProjectName -Environment $Environment

aws ec2 modify-subnet-attribute `
    --subnet-id $PublicSubnet2Id `
    --map-public-ip-on-launch `
    --region $Region

# Create Private Subnet 1
Write-Host "`n=== Creating Private Subnet 1 ($Az1) ===" -ForegroundColor Yellow

$PrivateSubnet1Id = aws ec2 create-subnet `
    --vpc-id $VpcId `
    --cidr-block $PrivateSubnet1Cidr `
    --availability-zone $Az1 `
    --region $Region `
    --tag-specifications "ResourceType=subnet,Tags=[{Key=Name,Value=$ProjectName-$Environment-private-subnet-1},{Key=Project,Value=$ProjectName},{Key=Environment,Value=$Environment},{Key=Type,Value=Private}]" `
    --query 'Subnet.SubnetId' `
    --output text

Write-Host "Private Subnet 1 created: $PrivateSubnet1Id" -ForegroundColor Green
Set-AwsConfig -Key "PRIVATE_SUBNET_1_ID" -Value $PrivateSubnet1Id -ProjectName $ProjectName -Environment $Environment

# Create Private Subnet 2
Write-Host "`n=== Creating Private Subnet 2 ($Az2) ===" -ForegroundColor Yellow

$PrivateSubnet2Id = aws ec2 create-subnet `
    --vpc-id $VpcId `
    --cidr-block $PrivateSubnet2Cidr `
    --availability-zone $Az2 `
    --region $Region `
    --tag-specifications "ResourceType=subnet,Tags=[{Key=Name,Value=$ProjectName-$Environment-private-subnet-2},{Key=Project,Value=$ProjectName},{Key=Environment,Value=$Environment},{Key=Type,Value=Private}]" `
    --query 'Subnet.SubnetId' `
    --output text

Write-Host "Private Subnet 2 created: $PrivateSubnet2Id" -ForegroundColor Green
Set-AwsConfig -Key "PRIVATE_SUBNET_2_ID" -Value $PrivateSubnet2Id -ProjectName $ProjectName -Environment $Environment

Write-Host "`n=== Subnet Setup Complete! ===" -ForegroundColor Cyan
Show-AwsConfig -ProjectName $ProjectName -Environment $Environment

Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  Run: .\03_create_security_groups.ps1"
