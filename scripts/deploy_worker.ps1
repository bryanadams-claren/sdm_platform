# Deploy to worker environment with worker Procfile
param(
    [string]$EnvName = "sdm-platform-dev-worker"
)

Write-Host "Deploying to worker environment: $EnvName" -ForegroundColor Cyan

# Verify Procfile.worker exists
if (-not (Test-Path "scripts/Procfile.worker")) {
    Write-Host "Error: Procfile.worker not found!" -ForegroundColor Red
    exit 1
}

# Copy worker Procfile
Copy-Item "scripts/Procfile.worker" "Procfile" -Force
Write-Host "Using Procfile.worker for deployment"

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
