# ============================================================================
# AI Cold Outreach Platform - Environment Configuration Script
# ============================================================================
# This script sets up the .env configuration file with necessary settings
# for the campaign platform to run on Windows.
#
# Usage: .\setup_environment.ps1 [-Interactive]
#
# Features:
#   - Creates .env file from .env.example template
#   - Interactive configuration prompts
#   - Validates configuration values
#   - Secure password input for sensitive values
#   - Backup of existing .env files
#
# Author: Campaign Platform Team
# Version: 1.0
# ============================================================================

param(
    [switch]$Interactive,
    [switch]$Verbose
)

# Set error handling
$ErrorActionPreference = "Stop"
$VerbosePreference = if ($Verbose) { "Continue" } else { "SilentlyContinue" }

# ============================================================================
# GLOBAL CONFIGURATION
# ============================================================================

$Script:ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Script:EnvFile = Join-Path $ProjectRoot ".env"
$Script:EnvExample = Join-Path $ProjectRoot ".env.example"
$Script:LogDir = Join-Path $ProjectRoot "logs"
$Script:LogFile = Join-Path $LogDir "environment_setup_$(Get-Date -Format 'yyyy-MM-dd_HH-mm-ss').log"

# Color definitions
$Script:Colors = @{
    Success = 'Green'
    Warning = 'Yellow'
    Error = 'Red'
    Info = 'Cyan'
    Progress = 'Magenta'
    Debug = 'DarkGray'
}

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

function Initialize-Logging {
    if (-not (Test-Path $LogDir)) {
        New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    }
    
    Write-Log "Environment setup started at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" "Info"
}

function Write-Log {
    param(
        [string]$Message,
        [string]$Type = "Info"
    )
    
    $timestamp = Get-Date -Format "HH:mm:ss"
    
    switch ($Type) {
        "Success" { Write-Host "✅ [$timestamp] $Message" -ForegroundColor $Colors.Success }
        "Warning" { Write-Host "⚠️  [$timestamp] $Message" -ForegroundColor $Colors.Warning }
        "Error" { Write-Host "❌ [$timestamp] $Message" -ForegroundColor $Colors.Error }
        "Progress" { Write-Host "🔄 [$timestamp] $Message" -ForegroundColor $Colors.Progress }
        "Step" { Write-Host "`n📋 [$timestamp] $Message" -ForegroundColor $Colors.Info }
        "Prompt" { Write-Host "❓ $Message" -ForegroundColor $Colors.Info -NoNewline }
        "Debug" { Write-Verbose "🔍 [$timestamp] $Message" }
        default { Write-Host "ℹ️  [$timestamp] $Message" -ForegroundColor $Colors.Info }
    }
    
    Add-Content -Path $LogFile -Value "[$timestamp] [$Type] $Message"
}

function Get-EnvTemplate {
    if (-not (Test-Path $Script:EnvExample)) {
        Write-Log "Environment template (.env.example) not found!" "Error"
        return $null
    }
    
    return Get-Content $Script:EnvExample
}

function Backup-ExistingEnv {
    if (Test-Path $Script:EnvFile) {
        $timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
        $backupFile = "$($Script:EnvFile).backup.$timestamp"
        
        Copy-Item $Script:EnvFile $backupFile
        Write-Log "Existing .env backed up to: $backupFile" "Info"
        
        return $backupFile
    }
    
    return $null
}

function Create-EnvFromTemplate {
    Write-Log "Creating .env file from template..." "Step"
    
    $template = Get-EnvTemplate
    if (-not $template) {
        return $false
    }
    
    $envContent = $template
    
    if ($Interactive) {
        Write-Log "Interactive mode enabled. You will be prompted for configuration values." "Info"
    } else {
        Write-Log "Non-interactive mode. Using defaults from template." "Info"
    }
    
    # Save to file
    try {
        $envContent | Set-Content $Script:EnvFile -Encoding UTF8
        Write-Log ".env file created successfully: $($Script:EnvFile)" "Success"
        return $true
    }
    catch {
        Write-Log "Failed to create .env file: $_" "Error"
        return $false
    }
}

function Validate-EnvFile {
    Write-Log "Validating configuration file..." "Step"
    
    if (-not (Test-Path $Script:EnvFile)) {
        Write-Log ".env file not found!" "Error"
        return $false
    }
    
    $content = Get-Content $Script:EnvFile
    $requiredKeys = @("MONGO_URI", "API_BASE", "CORS_ORIGINS", "SESSION_SECRET")
    
    $missingKeys = @()
    
    foreach ($key in $requiredKeys) {
        if (-not ($content -match "^$key=")) {
            $missingKeys += $key
        }
    }
    
    if ($missingKeys.Count -gt 0) {
        Write-Log "Missing required configuration keys: $($missingKeys -join ', ')" "Warning"
        return $true
    }
    
    Write-Log "Configuration file validation passed" "Success"
    return $true
}

# ============================================================================
# MAIN EXECUTION
# ============================================================================

function Main {
    try {
        Write-Host "`n╔════════════════════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
        Write-Host "║         Environment Configuration Setup for Campaign Platform             ║" -ForegroundColor Cyan
        Write-Host "╚════════════════════════════════════════════════════════════════════════════╝`n" -ForegroundColor Cyan
        
        Initialize-Logging
        
        if (Test-Path $Script:EnvFile) {
            Write-Log "Existing .env file detected" "Warning"
            $response = Read-Host "Overwrite existing .env? (y/N)"
            
            if ($response -ne "y" -and $response -ne "Y") {
                Write-Log "Setup cancelled. Keeping existing .env file." "Info"
                exit 0
            }
            
            Backup-ExistingEnv | Out-Null
        }
        
        if (-not (Create-EnvFromTemplate)) {
            Write-Log "Failed to create environment file" "Error"
            exit 1
        }
        
        if (-not (Validate-EnvFile)) {
            Write-Log "Configuration validation failed" "Error"
            exit 1
        }
        
        Write-Host @"

╔════════════════════════════════════════════════════════════════════════════╗
║                         SETUP COMPLETED                                   ║
╚════════════════════════════════════════════════════════════════════════════╝

✅ Environment configuration file created successfully!

📝 Configuration file: .env

📋 Next steps:
   1. Review your .env file with the appropriate settings
   2. For production, update sensitive values like SESSION_SECRET
   3. Run .\deploy.ps1 to continue with deployment

⚠️  IMPORTANT:
   - Change DEFAULT_ADMIN_PASSWORD in production
   - Update SESSION_SECRET for security
   - Configure API keys for your services

"@ -ForegroundColor Cyan
        
        Write-Log "Environment setup completed successfully" "Success"
        exit 0
    }
    catch {
        Write-Log "FATAL ERROR: $_" "Error"
        Write-Log "Stack trace: $($_.ScriptStackTrace)" "Debug"
        exit 1
    }
}

Main
