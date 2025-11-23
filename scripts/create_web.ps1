# Create Elastic Beanstalk environment with load balancer
param(
    [string]$EnvName = "sdm-platform-dev-web"
)

Write-Host "Creating EB environment for web workers: $EnvName" -ForegroundColor Cyan

uv run eb create $EnvName `
  --instance_type t3.small `
  --vpc.id vpc-0ea9b7f4341e4121e `
  --vpc.ec2subnets subnet-0d8fdf6b575253e49,subnet-036659884bdb99a58 `
  --vpc.elbsubnets subnet-0d8fdf6b575253e49,subnet-036659884bdb99a58 `
  --vpc.elbpublic `
  --vpc.publicip `
  --vpc.securitygroups sg-01980717819d4a489 `
  --instance_profile aws-elasticbeanstalk-ec2-role `
  --elb-type application `
  --scale 1

if ($LASTEXITCODE -eq 0) {
    Write-Host "`Web environment created successfully!" -ForegroundColor Green
    Write-Host "Check status with: uv run eb status $EnvName"
} else {
    Write-Host "`nFailed to create web environment" -ForegroundColor Red
    exit 1
}
