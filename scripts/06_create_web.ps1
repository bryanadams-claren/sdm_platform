# Create Elastic Beanstalk web environment
param(
    [string]$EnvName,
    [string]$VpcId,
    [string]$EbSgId,
    [string]$PublicSubnet1Id,
    [string]$PublicSubnet2Id,
    [string]$ProjectName = "sdm-platform",
    [string]$Environment = "dev"
)

# Import helper functions
. "$PSScriptRoot\aws_config_helpers.ps1"

# Load config if not provided
if (-not $VpcId) {
    $VpcId = Get-AwsConfig -Key "VPC_ID" -ProjectName $ProjectName -Environment $Environment
}
if (-not $EbSgId) {
    $EbSgId = Get-AwsConfig -Key "EB_SG_ID" -ProjectName $ProjectName -Environment $Environment
}
if (-not $PublicSubnet1Id) {
    $PublicSubnet1Id = Get-AwsConfig -Key "PUBLIC_SUBNET_1_ID" -ProjectName $ProjectName -Environment $Environment
}
if (-not $PublicSubnet2Id) {
    $PublicSubnet2Id = Get-AwsConfig -Key "PUBLIC_SUBNET_2_ID" -ProjectName $ProjectName -Environment $Environment
}
if (-not $EnvName) {
    $EnvName = "$ProjectName-$Environment-web"
}

if (-not $VpcId -or -not $EbSgId -or -not $PublicSubnet1Id -or -not $PublicSubnet2Id) {
    Write-Host "Error: Missing required configuration. Run setup scripts first." -ForegroundColor Red
    Write-Host "  VPC_ID: $VpcId" -ForegroundColor Yellow
    Write-Host "  EB_SG_ID: $EbSgId" -ForegroundColor Yellow
    Write-Host "  PUBLIC_SUBNET_1_ID: $PublicSubnet1Id" -ForegroundColor Yellow
    Write-Host "  PUBLIC_SUBNET_2_ID: $PublicSubnet2Id" -ForegroundColor Yellow
    exit 1
}

Write-Host "Creating EB web environment: $EnvName" -ForegroundColor Cyan
Write-Host "Using VPC: $VpcId" -ForegroundColor Gray
Write-Host "Using Security Group: $EbSgId" -ForegroundColor Gray
Write-Host "Using Subnets: $PublicSubnet1Id, $PublicSubnet2Id" -ForegroundColor Gray

uv run eb create $EnvName `
  --instance_type t3.small `
  --vpc.id $VpcId `
  --vpc.ec2subnets "$PublicSubnet1Id,$PublicSubnet2Id" `
  --vpc.elbsubnets "$PublicSubnet1Id,$PublicSubnet2Id" `
  --vpc.elbpublic `
  --vpc.publicip `
  --vpc.securitygroups $EbSgId `
  --instance_profile aws-elasticbeanstalk-ec2-role `
  --elb-type application `
  --scale 1

if ($LASTEXITCODE -eq 0) {
    Write-Host "`nWeb environment created successfully!" -ForegroundColor Green
    Write-Host "Environment will auto-detect and use web Procfile"
    Set-AwsConfig -Key "WEB_ENV_NAME" -Value $EnvName -ProjectName $ProjectName -Environment $Environment
} else {
    Write-Host "`nFailed to create web environment" -ForegroundColor Red
    exit 1
}
