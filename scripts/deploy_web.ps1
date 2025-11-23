# Deploy to web environment with web Procfile
param(
    [string]$EnvName = "sdm-platform-dev-web"
)

Write-Host "Deploying to web environment: $EnvName" -ForegroundColor Cyan

# Verify Procfile.web exists
if (-not (Test-Path "scripts/Procfile.web")) {
    Write-Host "Error: Procfile.web not found!" -ForegroundColor Red
    exit 1
}

# Copy web Procfile
Copy-Item "scripts/Procfile.web" "Procfile" -Force
Write-Host "Using Procfile.web for deployment"

try {
    # Deploy
    uv run eb deploy $EnvName

    if ($LASTEXITCODE -eq 0) {
        Write-Host "`nDeployment successful!" -ForegroundColor Green
    } else {
        Write-Host "`nDeployment failed" -ForegroundColor Red
        exit 1
    }
} finally {
    # Clean up generated Procfile
    if (Test-Path "Procfile") {
        Remove-Item "Procfile" -Force
        Write-Host "Cleaned up generated Procfile"
    }
}
