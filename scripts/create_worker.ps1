# Create Elastic Beanstalk worker environment
param(
    [string]$EnvName = "sdm-platform-dev-worker"
)

Write-Host "Creating EB worker environment: $EnvName" -ForegroundColor Cyan

uv run eb create $EnvName `
  --single `
  --instance_type t3.small `
  --vpc.id vpc-0ea9b7f4341e4121e `
  --vpc.ec2subnets subnet-0d8fdf6b575253e49,subnet-036659884bdb99a58 `
  --vpc.publicip `
  --vpc.securitygroups sg-01980717819d4a489 `
  --instance_profile aws-elasticbeanstalk-ec2-role

if ($LASTEXITCODE -eq 0) {
    Write-Host "`nWorker environment created successfully!" -ForegroundColor Green
    Write-Host "Environment will auto-detect and use worker Procfile"
} else {
    Write-Host "`nFailed to create worker environment" -ForegroundColor Red
    exit 1
}
