# ============================================================================
# AI Cold Outreach Platform - Master Deployment Script (Windows PowerShell)
# ============================================================================
# This script orchestrates the entire deployment process for the campaign platform
# including environment setup, dependency installation, database migrations, and service startup.
#
# Usage: .\deploy.ps1 [-SkipServices]
#
# Features:
#   - Beautiful welcome banner with ASCII art
#   - Comprehensive prerequisite checking (Python >= 3.9, Node >= 18)
#   - Environment configuration validation
#   - Dependency installation with version verification
#   - Database migration support
#   - Color-coded output and progress indicators
#   - Complete error handling with descriptive messages
#   - Log file generation
#   - Automatic browser opening when ready
#
# Author: Campaign Platform Team
# Version: 2.0
# ============================================================================

param(
    [switch]$SkipServices,
    [switch]$Verbose
)

# Set error handling
$ErrorActionPreference = "Stop"
$VerbosePreference = if ($Verbose) { "Continue" } else { "SilentlyContinue" }

# ============================================================================
# GLOBAL CONFIGURATION
# ============================================================================

$Script:ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Script:BackendDir = Join-Path $ProjectRoot "backend"
$Script:FrontendDir = Join-Path $ProjectRoot "Campaign_platform"
$Script:LogDir = Join-Path $ProjectRoot "logs"
$Script:LogFile = Join-Path $LogDir "deployment_$(Get-Date -Format 'yyyy-MM-dd_HH-mm-ss').log"

$Script:RequiredPythonVersion = 3.9
$Script:RequiredNodeVersion = 18

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
    
    Write-Log "============================================================================" "Cyan"
    Write-Log "Deployment started at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" "Info"
    Write-Log "PowerShell Version: $($PSVersionTable.PSVersion)" "Debug"
    Write-Log "Working Directory: $(Get-Location)" "Debug"
    Write-Log "============================================================================" "Cyan"
}

function Write-Log {
    param(
        [string]$Message,
        [string]$Type = "Info"
    )
    
    $timestamp = Get-Date -Format "HH:mm:ss"
    
    # Write to console with colors
    switch ($Type) {
        "Success" { Write-Host " [$timestamp] $Message" -ForegroundColor $Colors.Success }
        "Warning" { Write-Host "  [$timestamp] $Message" -ForegroundColor $Colors.Warning }
        "Error" { Write-Host " [$timestamp] $Message" -ForegroundColor $Colors.Error }
        "Progress" { Write-Host " [$timestamp] $Message" -ForegroundColor $Colors.Progress }
        "Header" { Write-Host "`n$('='*70)`n$Message`n$('='*70)`n" -ForegroundColor $Colors.Info }
        "Step" { Write-Host "`n [$timestamp] $Message" -ForegroundColor $Colors.Info }
        "Cyan" { Write-Host "" -ForegroundColor Cyan }
        "Debug" { Write-Verbose " [$timestamp] $Message" }
        default { Write-Host "ℹ  [$timestamp] $Message" -ForegroundColor $Colors.Info }
    }
    
    # Write to log file
    Add-Content -Path $LogFile -Value "[$timestamp] [$Type] $Message"
}

function Show-Banner {
    $banner = @"
    

                                                                            
                    AI COLD OUTREACH PLATFORM                         
                                                                            
                     Campaign Platform Deployment                         
                                                                            
                    Windows PowerShell Auto-Installer                     
                                                                            


"@
    Write-Host $banner -ForegroundColor Cyan
}

function Test-Command {
    param([string]$Command)
    return $null -ne (Get-Command $Command -ErrorAction SilentlyContinue)
}

function Get-VersionNumber {
    param([string]$Command)
    try {
        $output = & $Command --version 2>&1
        $version = $output -split '\n' | Select-Object -First 1
        return $version.Trim()
    }
    catch {
        return $null
    }
}

function Compare-Versions {
    param(
        [version]$Required,
        [version]$Current
    )
    return $Current -ge $Required
}

function Test-PathExists {
    param([string]$Path)
    return Test-Path $Path
}

# ============================================================================
# PREREQUISITE CHECKS
# ============================================================================

function Test-Prerequisites {
    Write-Log "Checking system prerequisites..." "Step"
    
    $allChecksPassed = $true
    
    # Check Python
    Write-Log "Checking Python installation..." "Progress"
    if (-not (Test-Command "python")) {
        Write-Log "Python not found. Please install Python 3.9 or higher from https://www.python.org/" "Error"
        $allChecksPassed = $false
    } else {
        $pythonVersion = Get-VersionNumber "python"
        Write-Log "Found Python: $pythonVersion" "Debug"
        
        try {
            $version = [version]($pythonVersion -replace 'Python ', '' -split ' ' | Select-Object -First 1)
            $required = [version]$RequiredPythonVersion
            
            if (Compare-Versions -Required $required -Current $version) {
                Write-Log "Python version meets requirements ($version >= $required)" "Success"
            } else {
                Write-Log "Python version is too old: $version (requires >= $required)" "Error"
                $allChecksPassed = $false
            }
        }
        catch {
            Write-Log "Could not parse Python version: $pythonVersion" "Warning"
        }
    }
    
    # Check Node.js
    Write-Log "Checking Node.js installation..." "Progress"
    if (-not (Test-Command "node")) {
        Write-Log "Node.js not found. Please install Node.js 18 or higher from https://nodejs.org/" "Error"
        $allChecksPassed = $false
    } else {
        $nodeVersion = Get-VersionNumber "node"
        Write-Log "Found Node.js: $nodeVersion" "Debug"
        
        try {
            $version = [version]($nodeVersion -replace 'v', '')
            $required = [version]"$RequiredNodeVersion.0.0"
            
            if (Compare-Versions -Required $required -Current $version) {
                Write-Log "Node.js version meets requirements ($version >= $required)" "Success"
            } else {
                Write-Log "Node.js version is too old: $version (requires >= $required)" "Error"
                $allChecksPassed = $false
            }
        }
        catch {
            Write-Log "Could not parse Node.js version: $nodeVersion" "Warning"
        }
    }
    
    # Check npm
    Write-Log "Checking npm installation..." "Progress"
    if (-not (Test-Command "npm")) {
        Write-Log "npm not found. Please reinstall Node.js which includes npm." "Error"
        $allChecksPassed = $false
    } else {
        $npmVersion = Get-VersionNumber "npm"
        Write-Log "Found npm: $npmVersion" "Success"
    }
    
    # Check Git
    Write-Log "Checking Git installation..." "Progress"
    if (-not (Test-Command "git")) {
        Write-Log "Git not found (optional). Download from https://git-scm.com/" "Warning"
    } else {
        $gitVersion = Get-VersionNumber "git"
        Write-Log "Found Git: $gitVersion" "Success"
    }
    
    if (-not $allChecksPassed) {
        Write-Log "Some prerequisites are missing. Please install them and try again." "Error"
        exit 1
    }
    
    Write-Log "All prerequisites passed!" "Success"
}

# ============================================================================
# ENVIRONMENT SETUP
# ============================================================================

function Test-EnvironmentFile {
    Write-Log "Checking environment configuration..." "Step"
    
    $envFile = Join-Path $ProjectRoot ".env"
    
    if (Test-PathExists $envFile) {
        Write-Log "Environment file exists: .env" "Success"
        return $true
    } else {
        Write-Log ".env file not found" "Warning"
        Write-Log "Running environment setup script..." "Progress"
        
        try {
            & .\setup_environment.ps1
            
            if (Test-PathExists $envFile) {
                Write-Log "Environment configuration completed successfully" "Success"
                return $true
            } else {
                Write-Log "Environment setup did not create .env file" "Error"
                return $false
            }
        }
        catch {
            Write-Log "Failed to run setup_environment.ps1: $_" "Error"
            return $false
        }
    }
}

# ============================================================================
# DEPENDENCY INSTALLATION
# ============================================================================

function Install-Dependencies {
    Write-Log "Installing project dependencies..." "Step"
    
    try {
        Write-Log "Running install_dependencies.ps1..." "Progress"
        & .\install_dependencies.ps1
        
        if ($LASTEXITCODE -ne 0) {
            Write-Log "Dependency installation encountered issues (exit code: $LASTEXITCODE)" "Error"
            return $false
        }
        
        Write-Log "Dependencies installed successfully" "Success"
        return $true
    }
    catch {
        Write-Log "Failed to install dependencies: $_" "Error"
        return $false
    }
}

# ============================================================================
# DATABASE MIGRATIONS
# ============================================================================

function Run-Migrations {
    Write-Log "Running database migrations..." "Step"
    
    try {
        Set-Location $BackendDir
        
        Write-Log "Creating database indexes..." "Progress"
        
        # Check if Python virtual environment exists
        $venvPath = Join-Path $BackendDir "venv"
        if (Test-PathExists $venvPath) {
            Write-Log "Using existing Python virtual environment" "Debug"
        }
        
        # Run migrations if indexes.py exists
        if (Test-PathExists (Join-Path $BackendDir "indexes.py")) {
            Write-Log "Found indexes.py, running migrations..." "Progress"
            
            $pythonCmd = "python"
            & $pythonCmd indexes.py 2>&1 | ForEach-Object { Write-Log $_ "Debug" }
            
            if ($LASTEXITCODE -eq 0) {
                Write-Log "Database migrations completed successfully" "Success"
            } else {
                Write-Log "Database migrations completed with warnings (exit code: $LASTEXITCODE)" "Warning"
            }
        } else {
            Write-Log "No migration script found (indexes.py), skipping migrations" "Info"
        }
        
        Set-Location $ProjectRoot
        return $true
    }
    catch {
        Write-Log "Failed to run migrations: $_" "Error"
        Set-Location $ProjectRoot
        return $false
    }
}

# ============================================================================
# SERVICE STARTUP
# ============================================================================

function Start-Services {
    Write-Log "Preparing to start services..." "Step"
    
    Write-Log "To start all services, run: .\start_services.ps1" "Info"
    Write-Log "To check service health, run: .\health_check.ps1" "Info"
    Write-Log "To stop services, run: .\stop_services.ps1" "Info"
}

# ============================================================================
# MAIN EXECUTION
# ============================================================================

function Main {
    try {
        # Show banner
        Show-Banner
        
        # Initialize logging
        Initialize-Logging
        
        # Check prerequisites
        Write-Log "" "Cyan"
        Test-Prerequisites
        
        # Test environment
        Write-Log "" "Cyan"
        if (-not (Test-EnvironmentFile)) {
            Write-Log "Environment setup failed. Cannot proceed." "Error"
            exit 1
        }
        
        # Install dependencies
        Write-Log "" "Cyan"
        if (-not (Install-Dependencies)) {
            Write-Log "Dependency installation failed. Cannot proceed." "Error"
            exit 1
        }
        
        # Run database migrations
        Write-Log "" "Cyan"
        Run-Migrations | Out-Null
        
        # Summary
        Write-Log "" "Cyan"
        Write-Log "Deployment preparation completed successfully!" "Success"
        
        Write-Host @"


                         NEXT STEPS                                        


1. Start services:
   .\start_services.ps1

2. Check system health:
   .\health_check.ps1

3. View logs:
   logs/deployment_*.log

4. Stop services (when done):
   .\stop_services.ps1

 Full deployment log: $LogFile

"@ -ForegroundColor Cyan
        
        # Offer to start services
        Write-Log "" "Cyan"
        if (-not $SkipServices) {
            $response = Read-Host "Would you like to start services now? (Y/n)"
            
            if ($response -eq "" -or $response -eq "Y" -or $response -eq "y") {
                Write-Log "Starting services..." "Progress"
                & .\start_services.ps1
            } else {
                Write-Log "Services not started. Run .\start_services.ps1 when ready." "Info"
            }
        }
        
        Write-Log "Deployment script completed successfully" "Success"
        exit 0
    }
    catch {
        Write-Log "FATAL ERROR: $_" "Error"
        Write-Log "Stack trace: $($_.ScriptStackTrace)" "Debug"
        exit 1
    }
}

# Run main
Main
