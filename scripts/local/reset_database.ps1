# Reset local PostgreSQL database for sdm_platform
# This script drops and recreates the database with proper permissions

$ErrorActionPreference = "Stop"

# Database configuration (matches .envs/.local/.django)
$DB_NAME = "sdm_platform"
$DB_USER = "sdm_user"
$DB_PASSWORD = "sdm_user_perspicacious"
$DB_HOST = "127.0.0.1"
$DB_PORT = "5432"

# Set PGPASSWORD environment variable to avoid password prompts
$env:PGPASSWORD = $DB_PASSWORD

Write-Host "Resetting database '$DB_NAME'..." -ForegroundColor Yellow

# Connect as the app user to postgres database to run admin commands
# Note: If this fails, you may need to connect as the postgres superuser instead
# In that case, change -U to "postgres" and set PGPASSWORD accordingly

try {
    # Terminate existing connections to the database
    Write-Host "Terminating existing connections..." -ForegroundColor Cyan
    psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d postgres -c @"
        SELECT pg_terminate_backend(pg_stat_activity.pid)
        FROM pg_stat_activity
        WHERE pg_stat_activity.datname = '$DB_NAME'
        AND pid <> pg_backend_pid();
"@

    # Drop the database
    Write-Host "Dropping database..." -ForegroundColor Cyan
    psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d postgres -c "DROP DATABASE IF EXISTS $DB_NAME;"

    # Create the database
    Write-Host "Creating database..." -ForegroundColor Cyan
    psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d postgres -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;"

    # Grant privileges
    Write-Host "Granting privileges..." -ForegroundColor Cyan
    psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;"

    Write-Host "Database reset complete!" -ForegroundColor Green

} catch {
    Write-Host "Error: $_" -ForegroundColor Red
    exit 1
} finally {
    # Clear the password from environment
    Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
}
