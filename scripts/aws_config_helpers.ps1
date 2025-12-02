# Helper functions for managing AWS infrastructure configuration

function Get-ConfigFilePath {
    param(
        [string]$ProjectName = "sdm-platform",
        [string]$Environment = "dev"
    )

    $scriptDir = Split-Path -Parent $PSCommandPath
    $projectRoot = Split-Path -Parent $scriptDir
    $configDir = Join-Path $projectRoot ".envs\.local"

    # Create directory if it doesn't exist
    if (-not (Test-Path $configDir)) {
        New-Item -ItemType Directory -Path $configDir -Force | Out-Null
    }

    return Join-Path $configDir ".aws-$ProjectName-$Environment"
}

function Set-AwsConfig {
    param(
        [string]$Key,
        [string]$Value,
        [string]$ProjectName = "sdm-platform",
        [string]$Environment = "dev"
    )

    $configFile = Get-ConfigFilePath -ProjectName $ProjectName -Environment $Environment

    # Read existing config
    $config = @{}
    if (Test-Path $configFile) {
        Get-Content $configFile | ForEach-Object {
            if ($_ -match '^([^=]+)=(.*)$') {
                $config[$matches[1]] = $matches[2]
            }
        }
    }

    # Update value
    $config[$Key] = $Value

    # Write back to file
    $config.GetEnumerator() | Sort-Object Name | ForEach-Object {
        "$($_.Name)=$($_.Value)"
    } | Set-Content $configFile

    Write-Host "Saved $Key to config file" -ForegroundColor Gray
}

function Get-AwsConfig {
    param(
        [string]$Key,
        [string]$ProjectName = "sdm-platform",
        [string]$Environment = "dev"
    )

    $configFile = Get-ConfigFilePath -ProjectName $ProjectName -Environment $Environment

    if (-not (Test-Path $configFile)) {
        return $null
    }

    $value = Get-Content $configFile | Where-Object { $_ -match "^$Key=" } | ForEach-Object {
        if ($_ -match "^$Key=(.*)$") {
            return $matches[1]
        }
    }

    return $value
}

function Show-AwsConfig {
    param(
        [string]$ProjectName = "sdm-platform",
        [string]$Environment = "dev"
    )

    $configFile = Get-ConfigFilePath -ProjectName $ProjectName -Environment $Environment

    if (-not (Test-Path $configFile)) {
        Write-Host "No configuration file found at: $configFile" -ForegroundColor Yellow
        return
    }

    Write-Host "`nAWS Infrastructure Configuration:" -ForegroundColor Cyan
    Write-Host "Config file: $configFile" -ForegroundColor Gray
    Write-Host ""
    Get-Content $configFile | ForEach-Object {
        Write-Host "  $_" -ForegroundColor Green
    }
    Write-Host ""
}
