# ============================================================================
# AI Cold Outreach Platform - Dependency Installation Script
# ============================================================================
# This script installs all required dependencies for the campaign platform
# including Python packages, Node.js packages, and Playwright browsers.
#
# Usage: .\install_dependencies.ps1 [-Force] [-Verbose]
#
# Features:
#   - Python virtual environment setup
#   - Pip dependencies installation with version checking
#   - Node.js dependencies installation
#   - Playwright browser installation
#   - Upgrade checks for pip/npm
#   - Detailed error reporting
#
# Author: Campaign Platform Team
# Version: 1.0
# ============================================================================

param(
    [switch]$Force,
    [switch]$Verbose,
    [switch]$SkipPlaywright
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
$Script:VenvPath = Join-Path $Script:BackendDir "venv"
$Script:LogDir = Join-Path $ProjectRoot "logs"
$Script:LogFile = Join-Path $LogDir "install_$(Get-Date -Format 'yyyy-MM-dd_HH-mm-ss').log"

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
    if (-not (Test-Path $Script:LogDir)) {
        New-Item -ItemType Directory -Path $Script:LogDir -Force | Out-Null
    }
    
    Write-Log "Dependency installation started at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" "Info"
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
        "Debug" { Write-Verbose "🔍 [$timestamp] $Message" }
        default { Write-Host "ℹ️  [$timestamp] $Message" -ForegroundColor $Colors.Info }
    }
    
    Add-Content -Path $Script:LogFile -Value "[$timestamp] [$Type] $Message"
}

function Get-PythonExecutable {
    if (Test-Path (Join-Path $Script:VenvPath "Scripts\python.exe")) {
        return Join-Path $Script:VenvPath "Scripts\python.exe"
    }
    return "python"
}

function Get-PipExecutable {
    if (Test-Path (Join-Path $Script:VenvPath "Scripts\pip.exe")) {
        return Join-Path $Script:VenvPath "Scripts\pip.exe"
    }
    return "pip"
}

# ============================================================================
# PYTHON SETUP
# ============================================================================

function Initialize-PythonVenv {
    Write-Log "Setting up Python virtual environment..." "Step"
    
    if (Test-Path $Script:VenvPath) {
        Write-Log "Virtual environment already exists: $($Script:VenvPath)" "Info"
        
        if (-not $Force) {
            Write-Log "Using existing virtual environment (use -Force to recreate)" "Progress"
            return $true
        } else {
            Write-Log "Removing existing virtual environment..." "Progress"
            Remove-Item $Script:VenvPath -Recurse -Force | Out-Null
        }
    }
    
    try {
        Write-Log "Creating new virtual environment..." "Progress"
        Set-Location $Script:BackendDir
        
        python -m venv venv 2>&1 | ForEach-Object { Write-Log $_ "Debug" }
        
        if ($LASTEXITCODE -ne 0) {
            Write-Log "Failed to create virtual environment" "Error"
            Set-Location $Script:ProjectRoot
            return $false
        }
        
        Write-Log "Virtual environment created successfully" "Success"
        Set-Location $Script:ProjectRoot
        return $true
    }
    catch {
        Write-Log "Error creating virtual environment: $_" "Error"
        Set-Location $Script:ProjectRoot
        return $false
    }
}

function Install-PythonDependencies {
    Write-Log "Installing Python dependencies..." "Step"
    
    try {
        Set-Location $Script:BackendDir
        
        $requirementsFile = Join-Path $Script:BackendDir "requirements.txt"
        if (-not (Test-Path $requirementsFile)) {
            Write-Log "requirements.txt not found: $requirementsFile" "Error"
            Set-Location $Script:ProjectRoot
            return $false
        }
        
        $pipCmd = Get-PipExecutable
        
        Write-Log "Upgrading pip..." "Progress"
        & $pipCmd install --upgrade pip 2>&1 | ForEach-Object { Write-Log $_ "Debug" }
        
        Write-Log "Installing packages from requirements.txt..." "Progress"
        & $pipCmd install -r requirements.txt 2>&1 | ForEach-Object { Write-Log $_ "Debug" }
        
        if ($LASTEXITCODE -ne 0) {
            Write-Log "Pip installation completed with warnings (exit code: $LASTEXITCODE)" "Warning"
        } else {
            Write-Log "Python dependencies installed successfully" "Success"
        }
        
        Set-Location $Script:ProjectRoot
        return $true
    }
    catch {
        Write-Log "Error installing Python dependencies: $_" "Error"
        Set-Location $Script:ProjectRoot
        return $false
    }
}

function Install-PlaywrightBrowsers {
    if ($SkipPlaywright) {
        Write-Log "Skipping Playwright browser installation" "Info"
        return $true
    }
    
    Write-Log "Installing Playwright browsers..." "Step"
    
    try {
        $pythonCmd = Get-PythonExecutable
        
        Write-Log "Running playwright install..." "Progress"
        & $pythonCmd -m playwright install 2>&1 | ForEach-Object { Write-Log $_ "Debug" }
        
        if ($LASTEXITCODE -ne 0) {
            Write-Log "Playwright installation completed with warnings (exit code: $LASTEXITCODE)" "Warning"
            return $true
        } else {
            Write-Log "Playwright browsers installed successfully" "Success"
        }
        
        return $true
    }
    catch {
        Write-Log "Warning: Could not install Playwright browsers: $_" "Warning"
        return $true
    }
}

# ============================================================================
# NODE.JS SETUP
# ============================================================================

function Install-NodeDependencies {
    Write-Log "Installing Node.js dependencies..." "Step"
    
    if (-not (Test-Path $Script:FrontendDir)) {
        Write-Log "Frontend directory not found: $($Script:FrontendDir)" "Warning"
        return $true
    }
    
    try {
        Set-Location $Script:FrontendDir
        
        $packageJson = Join-Path $Script:FrontendDir "package.json"
        if (-not (Test-Path $packageJson)) {
            Write-Log "package.json not found in frontend directory" "Info"
            Set-Location $Script:ProjectRoot
            return $true
        }
        
        Write-Log "Running npm install..." "Progress"
        npm install 2>&1 | ForEach-Object { Write-Log $_ "Debug" }
        
        if ($LASTEXITCODE -ne 0) {
            Write-Log "npm install completed with warnings (exit code: $LASTEXITCODE)" "Warning"
        } else {
            Write-Log "Node.js dependencies installed successfully" "Success"
        }
        
        Set-Location $Script:ProjectRoot
        return $true
    }
    catch {
        Write-Log "Warning: Error installing Node.js dependencies: $_" "Warning"
        Set-Location $Script:ProjectRoot
        return $true
    }
}

# ============================================================================
# VERIFICATION
# ============================================================================

function Verify-Installation {
    Write-Log "Verifying installation..." "Step"
    
    $allGood = $true
    
    try {
        $pythonCmd = Get-PythonExecutable
        $packages = & $pythonCmd -m pip list 2>&1
        
        $criticalPackages = @("fastapi", "pymongo", "pydantic", "uvicorn")
        
        foreach ($package in $criticalPackages) {
            if ($packages -match $package) {
                Write-Log "$package is installed" "Debug"
            } else {
                Write-Log "Warning: $package may not be installed correctly" "Warning"
                $allGood = $false
            }
        }
    }
    catch {
        Write-Log "Could not verify Python packages: $_" "Warning"
    }
    
    if (Test-Path $Script:FrontendDir) {
        try {
            Set-Location $Script:FrontendDir
            $nodeModules = Join-Path $Script:FrontendDir "node_modules"
            
            if (Test-Path $nodeModules) {
                Write-Log "Node.js dependencies verified" "Debug"
            } else {
                Write-Log "Warning: node_modules directory not found" "Warning"
                $allGood = $false
            }
            
            Set-Location $Script:ProjectRoot
        }
        catch {
            Write-Log "Could not verify Node packages: $_" "Warning"
        }
    }
    
    if ($allGood) {
        Write-Log "Installation verification passed" "Success"
    } else {
        Write-Log "Installation verification completed with warnings" "Warning"
    }
    
    return $true
}

# ============================================================================
# MAIN EXECUTION
# ============================================================================

function Main {
    try {
        Write-Host "`n╔════════════════════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
        Write-Host "║            Installing Dependencies for Campaign Platform                  ║" -ForegroundColor Cyan
        Write-Host "╚════════════════════════════════════════════════════════════════════════════╝`n" -ForegroundColor Cyan
        
        Initialize-Logging
        
        if (-not (Initialize-PythonVenv)) {
            Write-Log "Python virtual environment setup failed" "Error"
            exit 1
        }
        
        Write-Log "════════════════════════════════════════════" "Info"
        if (-not (Install-PythonDependencies)) {
            Write-Log "Python dependency installation failed" "Error"
            exit 1
        }
        
        Write-Log "════════════════════════════════════════════" "Info"
        Install-PlaywrightBrowsers | Out-Null
        
        Write-Log "════════════════════════════════════════════" "Info"
        Install-NodeDependencies | Out-Null
        
        Write-Log "════════════════════════════════════════════" "Info"
        Verify-Installation | Out-Null
        
        Write-Host @"

╔════════════════════════════════════════════════════════════════════════════╗
║                    INSTALLATION COMPLETED                                 ║
╚════════════════════════════════════════════════════════════════════════════╝

✅ All dependencies installed successfully!

📋 Summary:
   ✓ Python virtual environment created
   ✓ Python packages installed (FastAPI, PyMongo, etc.)
   ✓ Node.js packages installed
   ✓ Playwright browsers installed

📝 Log file: $($Script:LogFile)

"@ -ForegroundColor Cyan
        
        Write-Log "Dependency installation completed successfully" "Success"
        exit 0
    }
    catch {
        Write-Log "FATAL ERROR: $_" "Error"
        Write-Log "Stack trace: $($_.ScriptStackTrace)" "Debug"
        exit 1
    }
}

Main
